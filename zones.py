"""Selectable zones of the configuration window (gui.py): simplified outlines and names.

    python zones.py      # regenerate zones.json from the official boundaries

zones.json is kept in the repository, so that the window starts offline and fast.
Coordinates are LV95 metres, rounded to 10 m; outlines are simplified to ~150 m,
which is plenty to pick a zone but must not be used to cut the map data.
"""
import json
from pathlib import Path

import shapely
from shapely.ops import polylabel

import config
import coverage

ZONES_FILE = Path(__file__).resolve().parent / "zones.json"
SIMPLIFY = 150  # m

# Names in fr, de, it, en
CANTON_NAMES = {
    "ZH": ("Zurich", "Zürich", "Zurigo", "Zurich"),
    "BE": ("Berne", "Bern", "Berna", "Bern"),
    "LU": ("Lucerne", "Luzern", "Lucerna", "Lucerne"),
    "UR": ("Uri", "Uri", "Uri", "Uri"),
    "SZ": ("Schwytz", "Schwyz", "Svitto", "Schwyz"),
    "OW": ("Obwald", "Obwalden", "Obvaldo", "Obwalden"),
    "NW": ("Nidwald", "Nidwalden", "Nidvaldo", "Nidwalden"),
    "GL": ("Glaris", "Glarus", "Glarona", "Glarus"),
    "ZG": ("Zoug", "Zug", "Zugo", "Zug"),
    "FR": ("Fribourg", "Freiburg", "Friburgo", "Fribourg"),
    "SO": ("Soleure", "Solothurn", "Soletta", "Solothurn"),
    "BS": ("Bâle-Ville", "Basel-Stadt", "Basilea Città", "Basel-Stadt"),
    "BL": ("Bâle-Campagne", "Basel-Landschaft", "Basilea Campagna", "Basel-Landschaft"),
    "SH": ("Schaffhouse", "Schaffhausen", "Sciaffusa", "Schaffhausen"),
    "AR": ("Appenzell Rh.-Ext.", "Appenzell Ausserrhoden", "Appenzello Esterno", "Appenzell Ausserrhoden"),
    "AI": ("Appenzell Rh.-Int.", "Appenzell Innerrhoden", "Appenzello Interno", "Appenzell Innerrhoden"),
    "SG": ("Saint-Gall", "St. Gallen", "San Gallo", "St. Gallen"),
    "GR": ("Grisons", "Graubünden", "Grigioni", "Grisons"),
    "AG": ("Argovie", "Aargau", "Argovia", "Aargau"),
    "TG": ("Thurgovie", "Thurgau", "Turgovia", "Thurgau"),
    "TI": ("Tessin", "Tessin", "Ticino", "Ticino"),
    "VD": ("Vaud", "Waadt", "Vaud", "Vaud"),
    "VS": ("Valais", "Wallis", "Vallese", "Valais"),
    "NE": ("Neuchâtel", "Neuenburg", "Neuchâtel", "Neuchâtel"),
    "GE": ("Genève", "Genf", "Ginevra", "Geneva"),
    "JU": ("Jura", "Jura", "Giura", "Jura"),
}
# Departments along the Swiss border, and Savoie for the Alps south of Haute-Savoie
DEPT_NAMES = {
    "01": ("Ain",) * 4,
    "25": ("Doubs",) * 4,
    "39": ("Jura",) * 4,
    "68": ("Haut-Rhin", "Haut-Rhin", "Alto Reno", "Haut-Rhin"),
    "73": ("Savoie", "Savoyen", "Savoia", "Savoie"),
    "74": ("Haute-Savoie", "Hochsavoyen", "Alta Savoia", "Haute-Savoie"),
    "90": ("Territoire de Belfort", "Territoire de Belfort", "Territorio di Belfort", "Territoire de Belfort"),
}
ITALY_NAMES = {
    "AO": ("Vallée d'Aoste", "Aostatal", "Valle d'Aosta", "Aosta Valley"),
    "VB": ("Verbano-Cusio-Ossola",) * 4,
    "VA": ("Varèse", "Varese", "Varese", "Varese"),
    "CO": ("Côme", "Como", "Como", "Como"),
    "SO": ("Sondrio",) * 4,
    "BZ": ("Bolzano", "Südtirol", "Bolzano", "South Tyrol"),
    "GP": ("Grand Paradis (Piémont)", "Gran Paradiso (Piemont)", "Gran Paradiso (Piemonte)",
           "Gran Paradiso (Piedmont)"),
}
NAMES = {"ch": CANTON_NAMES, "fr": DEPT_NAMES, "it": ITALY_NAMES}
NAME_LANGS = ("fr", "de", "it", "en")


def _zone(country, code, geom):
    geom = shapely.make_valid(shapely.simplify(geom, SIMPLIFY))
    polys = [p for p in getattr(geom, "geoms", [geom]) if p.geom_type == "Polygon" and p.area > 1e6]
    # Label in the largest part, at the point farthest from its edges
    label = polylabel(max(polys, key=lambda p: p.area), tolerance=200)
    rnd = lambda cs: [[round(x, -1), round(y, -1)] for x, y in cs]
    return {"country": country, "code": code, "label": [round(label.x, -1), round(label.y, -1)],
            "area_km2": round(sum(p.area for p in polys) / 1e6),
            "polygons": [[rnd(p.exterior.coords)] + [rnd(r.coords) for r in p.interiors] for p in polys]}


def make():
    zones = []
    for code in config.CANTONS:
        print(f"canton {code}")
        geom = coverage.boundary("ch.swisstopo.swissboundaries3d-kanton-flaeche.fill", "ak", code)
        zones.append(_zone("ch", code, geom))
    for code in DEPT_NAMES:
        print(f"department {code}")
        zones.append(_zone("fr", code, coverage.department(code)))
    for code in ITALY_NAMES:
        print(f"Italian zone {code}")
        zones.append(_zone("it", code, coverage.italy_zone(code)))
    ZONES_FILE.write_text(json.dumps(zones, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(zones)} zones -> {ZONES_FILE} ({ZONES_FILE.stat().st_size / 1e3:.0f} kB)")


def load() -> list[dict]:
    return json.loads(ZONES_FILE.read_text(encoding="utf-8"))


def name(zone: dict, lang: str) -> str:
    return NAMES[zone["country"]][zone["code"]][NAME_LANGS.index(lang)]


if __name__ == "__main__":
    make()
