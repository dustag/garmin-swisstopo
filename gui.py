"""Configuration window: pick the zones on a map, set the options and build the maps.

    python gui.py

Downloads and builds run download.py and build.py in a child process whose output
is shown in the window. Packaged (frozen) builds run the same executable with a
"download" or "build" argument instead of the scripts.
"""
import importlib
import math
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QProcess, QProcessEnvironment, QRectF, QSettings, Qt, QUrl, Signal
from PySide6.QtGui import (QBrush, QColor, QDesktopServices, QFont, QFontDatabase, QFontMetricsF, QPainter,
                           QPainterPath, QPainterPathStroker, QPen, QPolygonF)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGraphicsItem,
                               QGraphicsPathItem, QGraphicsScene, QGraphicsView, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QSpinBox, QSplitter, QToolButton, QVBoxLayout, QWidget)

import shapely

import config
import coverage
import zones

REPO_DIR = Path(__file__).resolve().parent
COUNTRY_COLORS = {"ch": QColor("#d52b1e"), "fr": QColor("#2f5fb3"), "it": QColor("#2e8b57")}
LANGUAGES = {"fr": "Français", "de": "Deutsch", "it": "Italiano", "rm": "Rumantsch", "en": "English"}
# Average size of a 10 km tile, base and winter overlay with hill shading, measured on the
# Switzerland + Haute-Savoie (1.82 MB) and Switzerland + Haute-Savoie + Italy (1.78 MB) maps
MB_PER_TILE = 1.8
PROGRESS = re.compile(r"\[?(\d+)\s*/\s*(\d+)\]?")


def thousands(n: int) -> str:
    return f"{n:,}".replace(",", " ")


# --- Map -----------------------------------------------------------------------------------

class ZoneItem(QGraphicsPathItem):
    """A selectable zone outline (scene units: LV95 metres, y axis pointing down)."""

    def __init__(self, zone: dict):
        path = QPainterPath()
        path.setFillRule(Qt.OddEvenFill)
        for polygon in zone["polygons"]:
            for ring in polygon:
                path.addPolygon(QPolygonF([QPointF(x, -y) for x, y in ring]))
                path.closeSubpath()
        super().__init__(path)
        self.zone = zone
        self.selected = False
        self.hovered = False
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{zone['name']} ({thousands(zone['area_km2'])} km²)")
        self.update_style()

    def update_style(self):
        color = COUNTRY_COLORS[self.zone["country"]]
        fill = QColor(color)
        fill.setAlpha(170 if self.selected else 90 if self.hovered else 30)
        pen = QPen(color.darker(130), 2 if self.selected else 1)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setBrush(QBrush(fill))
        self.setZValue(2 if self.selected else 1)

    def hoverEnterEvent(self, event):
        self.hovered = True
        self.update_style()

    def hoverLeaveEvent(self, event):
        self.hovered = False
        self.update_style()


class LabelItem(QGraphicsItem):
    """Zone name drawn at a constant size with a halo; shows the code when the name does not fit."""

    FONT_SIZE = 9  # pt

    def __init__(self, zone: dict):
        super().__init__()
        self.zone = zone
        self.font = QFont()
        self.font.setPointSizeF(self.FONT_SIZE)
        self.font.setBold(True)
        self.metrics = QFontMetricsF(self.font)
        self.text = zone["name"]
        self.setPos(zone["label"][0], -zone["label"][1])
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setZValue(10)

    def fit(self, scale: float):
        """Pick the text for a view scale (pixels per metre)."""
        room = math.sqrt(self.zone["area_km2"] * 1e6) * scale * 1.3
        for text in (self.zone["name"], self.zone["code"]):
            if self.metrics.horizontalAdvance(text) < room:
                self.prepareGeometryChange()
                self.text = text
                self.setVisible(True)
                return
        self.setVisible(False)

    def boundingRect(self):
        w, h = self.metrics.horizontalAdvance(self.text) + 6, self.metrics.height() + 6
        return QRectF(-w / 2, -h / 2, w, h)

    def paint(self, painter, option, widget=None):
        path = QPainterPath()
        path.addText(-self.metrics.horizontalAdvance(self.text) / 2,
                     (self.metrics.ascent() - self.metrics.descent()) / 2, self.font, self.text)
        palette = QApplication.palette()
        painter.setRenderHint(QPainter.Antialiasing)
        halo = QPainterPathStroker()
        halo.setWidth(3)
        painter.fillPath(halo.createStroke(path), palette.base())
        painter.fillPath(path, palette.text())


class MapView(QGraphicsView):
    """Zone map: wheel to zoom, drag to pan, click to select or deselect a zone."""

    selection_changed = Signal()

    def __init__(self, zone_list: list[dict]):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.items_by_key = {}
        self.labels = []
        for zone in zone_list:
            item = ZoneItem(zone)
            self.scene().addItem(item)
            self.items_by_key[(zone["country"], zone["code"])] = item
            label = LabelItem(zone)
            self.scene().addItem(label)
            self.labels.append(label)
        self.home = self.scene().itemsBoundingRect().adjusted(-5000, -5000, 5000, 5000)
        self.setSceneRect(self.home.adjusted(-100_000, -100_000, 100_000, 100_000))
        self.setRenderHint(QPainter.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._press = None
        self._fitted = False

    # Selection

    def selected(self) -> list[dict]:
        return [i.zone for i in self.items_by_key.values() if i.selected]

    def set_selected(self, keys, selected=True, exclusive=False):
        for key, item in self.items_by_key.items():
            if key in keys:
                item.selected = selected
            elif exclusive:
                item.selected = False
            item.update_style()
        self.selection_changed.emit()

    # Navigation

    def fit_home(self):
        self.fitInView(self.home, Qt.KeepAspectRatio)
        self.fit_labels()

    def fit_labels(self):
        for label in self.labels:
            label.fit(self.transform().m11())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._fitted:
            self.fit_home()
            self._fitted = True

    def wheelEvent(self, event):
        factor = 1.25 ** (event.angleDelta().y() / 120)
        scale = self.transform().m11() * factor
        if 1e-4 < scale < 0.05:  # from the whole map to a few km across
            self.scale(factor, factor)
            self.fit_labels()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press = self._last = event.position()
            self._dragged = False

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)   # hover
        if self._press is None:
            return
        if (event.position() - self._press).manhattanLength() > 4:
            self._dragged = True
            self.viewport().setCursor(Qt.ClosedHandCursor)
        if self._dragged:
            delta = event.position() - self._last
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - round(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - round(delta.y()))
        self._last = event.position()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self._press is None:
            return
        if not self._dragged:
            item = next((i for i in self.items(event.position().toPoint()) if isinstance(i, ZoneItem)), None)
            if item:
                item.selected = not item.selected
                item.update_style()
                self.selection_changed.emit()
        self.viewport().unsetCursor()
        self._press = None


# --- Window --------------------------------------------------------------------------------

def coverage_spec(selected: list[dict]) -> str:
    """Coverage spec (see coverage.resolve) for the selected zones, in a stable order."""
    codes = {c: [z["code"] for z in selected if z["country"] == c] for c in COUNTRY_COLORS}
    parts = []
    if set(codes["ch"]) == set(config.CANTONS):
        parts.append("switzerland")
    elif codes["ch"]:
        parts.append("canton:" + ",".join(sorted(codes["ch"], key=config.CANTONS.index)))
    if codes["fr"]:
        parts.append("dept:" + ",".join(sorted(codes["fr"])))
    if codes["it"]:
        parts.append("it:" + ",".join(sorted(codes["it"], key=list(zones.ITALY_NAMES).index)))
    return "+".join(parts)


def estimate_mb(selected: list[dict]) -> float:
    """Size of the base map and winter overlay together, from the number of grid tiles."""
    geom = shapely.union_all([shapely.Polygon(p[0], p[1:]) for z in selected for p in z["polygons"]])
    return len(coverage.tiles_for(geom)) * MB_PER_TILE


def file_size(mb: float) -> str:
    """Size in MB or GB (SI), with one decimal below 10, French decimal comma."""
    value, unit = (mb / 1000, "Go") if mb >= 1000 else (mb, "Mo")
    digits = max(0, 1 - math.floor(math.log10(max(value, 1))))
    return f"{round(value, digits):.{digits}f} {unit}".replace(".", ",")


def child_command(step: str, args: list[str]) -> tuple[str, list[str]]:
    """Program and arguments running download.py or build.py."""
    if getattr(sys, "frozen", False):
        return sys.executable, [step] + args
    return sys.executable, ["-u", str(REPO_DIR / f"{step}.py")] + args


def last_segment(line: str) -> str:
    """What a terminal would show of a line rewritten with carriage returns."""
    return line.rstrip("\r").split("\r")[-1].rstrip()


class PathEdit(QWidget):
    """Line edit with a browse button, for a folder or a file."""

    def __init__(self, text="", placeholder="", folder=True):
        super().__init__()
        self.edit = QLineEdit(text)
        self.edit.setPlaceholderText(placeholder)
        browse = QToolButton(text="…")
        browse.clicked.connect(self.browse)
        self.folder = folder
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit)
        layout.addWidget(browse)

    def text(self):
        return self.edit.text().strip()

    def browse(self):
        if self.folder:
            path = QFileDialog.getExistingDirectory(self, "Choisir un dossier", self.text())
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Choisir un fichier", self.text())
        if path:
            self.edit.setText(str(Path(path)))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Cartes Garmin swisstopo")
        self.settings = QSettings("swisstopo-garmin", "gui")
        self.process = None
        self.steps = []
        self._partial = ""

        self.map = MapView(zones.load())
        self.map.selection_changed.connect(self.update_summary)

        # Zones
        self.summary = QLabel(wordWrap=True)
        whole = QPushButton("Toute la Suisse")
        whole.clicked.connect(lambda: self.map.set_selected({("ch", c) for c in config.CANTONS}))
        clear = QPushButton("Tout désélectionner")
        clear.clicked.connect(lambda: self.map.set_selected(set(), exclusive=True))
        home = QPushButton("Recentrer")
        home.clicked.connect(self.map.fit_home)
        buttons = QHBoxLayout()
        for b in (whole, clear, home):
            buttons.addWidget(b)
        zone_box = QGroupBox("Zones")
        zone_layout = QVBoxLayout(zone_box)
        zone_layout.addWidget(QLabel("Cliquez sur la carte pour choisir les zones. "
                                     "Molette pour zoomer, glisser pour se déplacer.", wordWrap=True))
        zone_layout.addWidget(self.summary)
        zone_layout.addLayout(buttons)

        # Options
        s = self.settings
        self.lang = QComboBox()
        for code, name in LANGUAGES.items():
            self.lang.addItem(name, code)
        self.lang.setCurrentIndex(list(LANGUAGES).index(s.value("lang", config.LANG)))
        self.dem = QCheckBox("Ombrage du relief", checked=s.value("dem", True, type=bool))
        self.data_dir = PathEdit(s.value("data_dir", str(config.DATA_DIR)))
        self.output_dir = PathEdit(s.value("output_dir", ""), "dans le dossier des données")
        options = QGroupBox("Options")
        form = QFormLayout(options)
        form.addRow("Langue des étiquettes", self.lang)
        form.addRow("", self.dem)
        form.addRow("Dossier des données", self.data_dir)
        form.addRow("Dossier des cartes", self.output_dir)

        self.java = PathEdit(s.value("java", config.JAVA), folder=False)
        self.jobs = QSpinBox(minimum=1, maximum=os.cpu_count() or 1)
        self.jobs.setValue(s.value("jobs", max(1, (os.cpu_count() or 2) - 1), type=int))
        self.force = QCheckBox("Reconstruire les tuiles déjà construites")
        advanced = QGroupBox("Avancé", visible=False)
        adv_form = QFormLayout(advanced)
        adv_form.addRow("Java", self.java)
        adv_form.addRow("Tuiles en parallèle", self.jobs)
        adv_form.addRow("", self.force)
        show_advanced = QCheckBox("Afficher les options avancées")
        show_advanced.toggled.connect(advanced.setVisible)
        form.addRow("", show_advanced)

        # Run
        self.start_button = QPushButton("Construire les cartes")
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(self.start)
        self.cancel_button = QPushButton("Annuler", enabled=False)
        self.cancel_button.clicked.connect(self.cancel)
        open_button = QPushButton("Ouvrir le dossier des cartes")
        open_button.clicked.connect(self.open_output)
        run_buttons = QHBoxLayout()
        run_buttons.addWidget(self.start_button)
        run_buttons.addWidget(self.cancel_button)
        run_buttons.addWidget(open_button)
        self.status = QLabel("Prêt.")
        self.progress = QProgressBar(textVisible=False)
        self.progress.setRange(0, 1)
        self.log = QPlainTextEdit(readOnly=True)
        self.log.setMaximumBlockCount(5000)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.addWidget(zone_box)
        side_layout.addWidget(options)
        side_layout.addWidget(advanced)
        side_layout.addLayout(run_buttons)
        side_layout.addWidget(self.status)
        side_layout.addWidget(self.progress)
        side_layout.addWidget(self.log, 1)

        splitter = QSplitter()
        splitter.addWidget(self.map)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)
        self.resize(1300, 800)
        if s.contains("geometry"):
            self.restoreGeometry(s.value("geometry"))

        keys = {tuple(k.split(":")) for k in s.value("zones", [], type=list)}
        self.map.set_selected(keys & set(self.map.items_by_key))

    # Settings

    def output_path(self) -> Path:
        return Path(self.output_dir.text() or Path(self.data_dir.text()) / "output").expanduser()

    def save_settings(self):
        s = self.settings
        s.setValue("zones", [f"{z['country']}:{z['code']}" for z in self.map.selected()])
        s.setValue("lang", self.lang.currentData())
        s.setValue("dem", self.dem.isChecked())
        s.setValue("data_dir", self.data_dir.text())
        s.setValue("output_dir", self.output_dir.text())
        s.setValue("java", self.java.text())
        s.setValue("jobs", self.jobs.value())
        s.setValue("geometry", self.saveGeometry())

    def update_summary(self):
        selected = self.map.selected()
        if not selected:
            self.summary.setText("<i>Aucune zone sélectionnée.</i>")
            return
        area = sum(z["area_km2"] for z in selected)
        self.summary.setText(f"Surface : <b>{thousands(area)} km²</b><br>"
                             f"Taille estimée : <b>≈ {file_size(estimate_mb(selected))}</b> (base et hiver)")

    # Run

    def environment(self) -> QProcessEnvironment:
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("DATA_DIR", self.data_dir.text())
        if self.output_dir.text():
            env.insert("OUTPUT_DIR", self.output_dir.text())
        env.insert("LANG_LABELS", self.lang.currentData())
        env.insert("JAVA_EXE", self.java.text() or "java")
        # The neighbours' data must include every selected zone
        selected = self.map.selected()
        depts = dict.fromkeys(config.FRANCE_DEPTS + [z["code"] for z in selected if z["country"] == "fr"])
        italy = dict.fromkeys(config.ITALY_ZONES + [z["code"] for z in selected if z["country"] == "it"])
        env.insert("FRANCE_DEPTS", ",".join(depts))
        env.insert("ITALY_ZONES", ",".join(italy))
        return env

    def start(self):
        spec = coverage_spec(self.map.selected())
        if not spec:
            QMessageBox.information(self, "Aucune zone", "Choisissez au moins une zone sur la carte.")
            return
        java = self.java.text() or "java"
        if not (shutil.which(java) or Path(java).is_file()):
            QMessageBox.warning(self, "Java introuvable",
                                "Java est nécessaire pour compiler les cartes (mkgmap).\n\n"
                                "Installez Java (par exemple Eclipse Temurin) ou indiquez "
                                "l'emplacement de java.exe dans les options avancées.")
            return
        self.save_settings()
        build_args = ["--coverage", spec, "--jobs", str(self.jobs.value())]
        if not self.dem.isChecked():
            build_args.append("--no-dem")
        if self.force.isChecked():
            build_args.append("--force")
        self.steps = [("Téléchargement des données", "download", ["--coverage", spec]),
                      ("Construction des cartes", "build", build_args)]
        self.log.clear()
        self.append_log(f"Couverture : {spec}")
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.next_step()

    def next_step(self):
        title, step, args = self.steps.pop(0)
        self.status.setText(title + "…")
        self.status.setStyleSheet("")
        self.progress.setRange(0, 0)
        self._partial = ""
        self.process = QProcess(self)
        self.process.setProcessEnvironment(self.environment())
        self.process.setWorkingDirectory(str(REPO_DIR))
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.step_finished)
        self.process.errorOccurred.connect(self.process_error)
        self.process.start(*child_command(step, args))

    def read_output(self):
        text = self._partial + bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace")
        lines = text.split("\n")
        self._partial = lines.pop()
        lines = [last_segment(line) for line in lines]
        for line in lines:
            self.append_log(line)
        # Progress lines ("\r  12 / 300", "[12/300] tile") update the bar
        for line in reversed(lines + [last_segment(self._partial)]):
            if m := PROGRESS.search(line):
                done, total = int(m[1]), int(m[2])
                if 0 < total and done <= total:
                    self.progress.setRange(0, total)
                    self.progress.setValue(done)
                break

    def append_log(self, line):
        self.log.appendPlainText(line)

    def step_finished(self, code, status):
        if self._partial:
            self.append_log(last_segment(self._partial))
        self.process = None
        if status == QProcess.NormalExit and code == 0 and self.steps:
            self.next_step()
        elif status == QProcess.NormalExit and code == 0:
            self.done(f"Cartes prêtes dans {self.output_path()}", ok=True)
        elif self.steps is None:
            self.done("Annulé.", ok=False)
        else:
            self.done(f"Échec (code {code}), voir le journal.", ok=False)

    def process_error(self, error):
        if error == QProcess.FailedToStart:
            self.process = None
            self.done("Impossible de lancer le programme.", ok=False)

    def done(self, message, ok):
        self.status.setText(message)
        self.status.setStyleSheet("" if ok else "color: #c0392b; font-weight: bold;")
        self.progress.setRange(0, 1)
        self.progress.setValue(1 if ok else 0)
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def cancel(self):
        if self.process is None:
            return
        self.steps = None
        pid = self.process.processId()
        if os.name == "nt":   # the build starts worker processes and Java: stop the whole tree
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        else:
            self.process.kill()

    def open_output(self):
        path = self.output_path()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def closeEvent(self, event):
        if self.process is not None:
            answer = QMessageBox.question(self, "Construction en cours",
                                          "Une construction est en cours. L'arrêter et quitter ?")
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.cancel()
            self.process.waitForFinished(5000)
        self.save_settings()
        event.accept()


def main():
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] in ("download", "build"):   # child process of a packaged build
        module = importlib.import_module(sys.argv[1])
        sys.argv = [f"{sys.argv[1]}.py"] + sys.argv[2:]
        sys.exit(module.main())
    app = QApplication(sys.argv)
    app.setApplicationDisplayName("Cartes Garmin swisstopo")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
