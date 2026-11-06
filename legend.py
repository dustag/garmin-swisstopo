"""Map legend: single source of truth for the mkgmap style and the TYP file.

Every object written to the OSM file carries a `k=<key>` tag; the matching
category defines its Garmin type, the minimum resolution at which it shows up
(24 = most zoomed in) and how it is drawn. Legend labels are translated in
LABELS and embedded in the TYP file for every supported language.
"""
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Cat:
    key: str
    kind: str              # "point" | "line" | "polygon"
    type: int
    res: int
    xpm: list[str]         # TYP Xpm block (DayXpm for points)
    extra: list[str] = field(default_factory=list)
    order: int = 1         # polygon draw order (higher = on top)
    name: str | None = "${name}"   # mkgmap label expression


# --- TYP drawing helpers ------------------------------------------------------

def solid(color):
    return ['Xpm="0 0 1 0"', f'"1 c {color}"']


def pattern(color, tile, bg="none"):
    """32x32 fill pattern repeating a tile (list of strings, 'x' = colour)."""
    h, w = len(tile), len(tile[0])
    rows = ["".join("x" if tile[r % h][c % w] == "x" else "." for c in range(32)) for r in range(32)]
    return ['Xpm="32 32 2 1"', f'"x c {color}"', f'". c {bg}"'] + [f'"{r}"' for r in rows]


def line(color, width, border=None, border_width=1):
    if border:
        return [f"LineWidth={width}", f"BorderWidth={border_width}",
                'Xpm="0 0 2 0"', f'"1 c {color}"', f'"2 c {border}"']
    return [f"LineWidth={width}", 'Xpm="0 0 1 0"', f'"1 c {color}"']


def bitmap_line(color, rows):
    """Line drawn from a 32 px long pattern; height = line width."""
    rows = [(r * 32)[:32] for r in rows]
    return ["UseOrientation=Y", f'Xpm="32 {len(rows)} 2 1"', f'"x c {color}"', '". c none"'] + \
           [f'"{r.replace("-", ".")}"' for r in rows]


def dashed(color, width, on, off):
    return bitmap_line(color, ["x" * on + "-" * off] * width)


def icon(rows, colors):
    """Point icon; colors maps a character to a colour, '.' is transparent."""
    head = [f'DayXpm="{len(rows[0])} {len(rows)} {len(colors) + 1} 1"']
    return head + [f'"{c} c {v}"' for c, v in colors.items()] + ['". c none"'] + [f'"{r}"' for r in rows]


TEXT_ONLY = icon(["."], {})

HATCH_DIAG = ["-" * i + "x" + "-" * (7 - i) for i in range(8)]
HATCH_DIAG_SPARSE = ["-" * i + "x" + "-" * (15 - i) for i in range(16)]
STIPPLE = ["x-", "-x"]
DOTS = ["x---", "----", "--x-", "----"]


# --- Base map (all seasons) -------------------------------------------------------

BASE = [
    # Polygons. "land" is an opaque background limited to Switzerland, so that the
    # map hides Garmin's own maps there but lets them show through abroad.
    Cat("land", "polygon", 0x01, 16, solid("#F7F5EE"), order=1, name=None),
    Cat("rock", "polygon", 0x53, 20, pattern("#C9C2B8", DOTS, "#E4E0DA"), order=2, name=None),
    Cat("scree", "polygon", 0x52, 20, pattern("#BDB5A8", ["x-----", "------", "---x--", "------"], "#EEEAE4"), order=2, name=None),
    Cat("glacier", "polygon", 0x4D, 18, solid("#DCEFFA"), order=3),
    Cat("forest", "polygon", 0x50, 18, solid("#B9DC9E"), order=3, name=None),
    Cat("scrub", "polygon", 0x51, 20, pattern("#9CC97F", DOTS, "#DCEFCB"), order=3, name=None),
    Cat("wetland", "polygon", 0x4C, 20, pattern("#5AA0D8", ["xxx-----", "--------", "----xxx-", "--------"], "#E8F3E0"), order=3, name=None),
    Cat("lake", "polygon", 0x3C, 18, solid("#9CCFF0"), order=4),
    Cat("river_area", "polygon", 0x46, 20, solid("#9CCFF0"), order=4, name=None),
    Cat("building", "polygon", 0x13, 22, solid("#5A5A5A"), order=5, name=None),

    # Contour lines (types 0x20-0x22: label in feet, converted by the device)
    Cat("contour_minor", "line", 0x20, 23, line("#C9A27E", 1), name='${ele|conv:"m=>ft"}'),
    Cat("contour_medium", "line", 0x21, 21, line("#B07D4E", 1), name='${ele|conv:"m=>ft"}'),
    Cat("contour_major", "line", 0x22, 20, line("#9A6535", 2), name='${ele|conv:"m=>ft"}'),

    # Hydrography
    Cat("stream", "line", 0x18, 21, line("#3D8FD6", 1)),
    Cat("river", "line", 0x1F, 19, line("#3D8FD6", 2)),

    # Transport
    Cat("road_major", "line", 0x02, 17, line("#F2A93B", 3, "#3C3C3C")),
    Cat("road", "line", 0x06, 19, line("#FFFFFF", 2, "#3C3C3C")),
    Cat("track", "line", 0x07, 21, line("#3C3C3C", 2)),
    Cat("path", "line", 0x16, 22, dashed("#3C3C3C", 1, 6, 3)),
    # Swiss hiking signage (yellow / white-red-white / white-blue-white); Italian
    # paths take the category matching their OpenStreetMap SAC scale
    Cat("hike_t1", "line", 0x0F, 21, dashed("#E0A100", 2, 8, 3)),
    Cat("hike_t2", "line", 0x10, 21, dashed("#E2001A", 2, 8, 3)),
    Cat("hike_t3", "line", 0x11, 21, dashed("#0055C8", 2, 5, 4)),
    # French marked routes: GR (red-white) and other routes (yellow), drawn over the paths
    Cat("hike_gr", "line", 0x12, 20, bitmap_line("#D7191C", ["x" * 8 + "-" * 2 + "x" * 4 + "-" * 2] * 2)),
    Cat("hike_pr", "line", 0x13, 21, bitmap_line("#E0A100", ["x" * 8 + "-" * 2 + "x" * 4 + "-" * 2] * 2)),
    Cat("rail", "line", 0x14, 18, line("#202020", 2)),
    Cat("aerialway", "line", 0x1A, 20, bitmap_line("#202020", ["-" * 15 + "x" + "-" * 16, "x" * 32, "-" * 15 + "x" + "-" * 16])),
    Cat("powerline", "line", 0x29, 22, line("#8C8C8C", 1)),

    # Points
    Cat("peak_major", "point", 0x6616, 19, icon(["...x...", "..xxx..", ".xxxxx.", "xxxxxxx"], {"x": "#202020"}),
        extra=["FontStyle=NormalFont"]),
    Cat("peak", "point", 0x6617, 21, icon(["..x..", ".xxx.", "xxxxx"], {"x": "#404040"}), extra=["FontStyle=SmallFont"]),
    Cat("pass", "point", 0x6618, 21, icon(["x...x", ".x.x.", ".x.x.", "x...x"], {"x": "#404040"}), extra=["FontStyle=SmallFont"]),
    Cat("hut", "point", 0x2B04, 19,
        icon(["...rr...", "..rrrr..", ".rrrrrr.", "rrrrrrrr", ".rwwwwr.", ".rwwwwr.", ".rrrrrr."], {"r": "#C8102E", "w": "#FFFFFF"}),
        extra=["FontStyle=NormalFont"]),
    Cat("settlement", "point", 0x0E00, 17, TEXT_ONLY, extra=["FontStyle=NormalFont"]),
    Cat("hamlet", "point", 0x1000, 20, TEXT_ONLY, extra=["FontStyle=SmallFont"]),
    Cat("locality", "point", 0x2800, 22, TEXT_ONLY, extra=["FontStyle=SmallFont", "DayCustomColor=#6A5A4A"]),
]

# --- Winter overlay (transparent) -------------------------------------------------

SKI = "#0033FF"
WINTER = [
    # Slopes over 30 deg (Swisstopo layer colours), half-transparent stipple
    Cat("slope_30", "polygon", 0x01, 21, pattern("#F5E100", STIPPLE), order=1, name=None),
    Cat("slope_35", "polygon", 0x02, 21, pattern("#F39200", STIPPLE), order=2, name=None),
    Cat("slope_40", "polygon", 0x03, 21, pattern("#E2001A", STIPPLE), order=3, name=None),
    Cat("slope_45", "polygon", 0x04, 21, pattern("#A0127F", STIPPLE), order=4, name=None),
    # Wildlife quiet zones and protection areas
    Cat("wildlife_binding", "polygon", 0x05, 19, pattern("#D00000", HATCH_DIAG), order=5),
    Cat("wildlife_advised", "polygon", 0x06, 19, pattern("#E07000", HATCH_DIAG_SPARSE), order=5),
    Cat("wildlife_edge_binding", "line", 0x05, 19, line("#D00000", 2), name=None),
    Cat("wildlife_edge_advised", "line", 0x06, 19, dashed("#E07000", 2, 6, 3), name=None),
    Cat("wildlife_route", "line", 0x0B, 21, dashed("#00A040", 2, 3, 2)),
    # Nature reserves and protected areas outside Switzerland (rules vary: check them before the trip)
    Cat("nature_reserve", "polygon", 0x07, 19, pattern("#2E8B57", HATCH_DIAG_SPARSE), order=5),
    Cat("nature_reserve_edge", "line", 0x0D, 19, dashed("#2E8B57", 2, 6, 3), name=None),
    # Routes (Swisstopo snow sports map colours)
    Cat("ski_route_label", "line", 0x01, 21, line(SKI, 1)),
    Cat("ski", "line", 0x02, 19, line(SKI, 3), name=None),
    Cat("ski_foot", "line", 0x03, 19, dashed(SKI, 3, 5, 3), name=None),
    Cat("ski_caution", "line", 0x04, 19, bitmap_line(SKI, ["x" * 10 + "-" * 6, "x" * 16, "x" * 10 + "-" * 6]), name=None),
    Cat("ski_up", "line", 0x07, 19, bitmap_line(SKI, ["--------x-------", "---------x------", "xxxxxxxxxxxxxxxx", "---------x------", "--------x-------"]), name=None),
    Cat("ski_down", "line", 0x08, 19, bitmap_line(SKI, ["--------x--x----", "---------x--x---", "xxxxxxxxxxxxxxxx", "---------x--x---", "--------x--x----"]), name=None),
    Cat("snowshoe", "line", 0x09, 19, dashed("#C2007A", 2, 7, 2), name=None),
    Cat("snowshoe_route_label", "line", 0x0A, 21, line("#C2007A", 1)),
    # Ski touring routes outside Switzerland: OpenStreetMap, and Camptocamp (track when
    # available, otherwise a point)
    Cat("ski_osm", "line", 0x0E, 19, dashed(SKI, 2, 3, 3)),
    Cat("ski_c2c", "line", 0x0C, 19, dashed(SKI, 2, 6, 2)),
    Cat("ski_c2c_point", "point", 0x6610, 20,
        icon(["..x..", ".xxx.", "xxxxx", ".xxx.", "..x.."], {"x": SKI}), extra=["FontStyle=SmallFont"]),
]

MAPS = {"base": BASE, "hiver": WINTER}


# --- Legend labels ----------------------------------------------------------------------

LANGS = ("fr", "de", "it", "en")
# Garmin language codes
GARMIN_LANG = {"fr": 0x01, "de": 0x02, "en": 0x04, "it": 0x05}

LABELS = {  # key: (fr, de, it, en)
    "land": ("Fond de carte", "Kartenhintergrund", "Sfondo", "Map background"),
    "rock": ("Rocher", "Fels", "Roccia", "Rock"),
    "scree": ("Éboulis", "Geröll", "Detriti", "Scree"),
    "glacier": ("Glacier", "Gletscher", "Ghiacciaio", "Glacier"),
    "forest": ("Forêt", "Wald", "Bosco", "Forest"),
    "scrub": ("Buissons", "Gebüsch", "Cespugli", "Scrub"),
    "wetland": ("Zone humide", "Feuchtgebiet", "Zona umida", "Wetland"),
    "lake": ("Lac", "See", "Lago", "Lake"),
    "river_area": ("Cours d'eau", "Fliessgewässer", "Corso d'acqua", "River"),
    "building": ("Bâtiment", "Gebäude", "Edificio", "Building"),
    "contour_minor": ("Courbe 10 m", "Höhenkurve 10 m", "Curva di livello 10 m", "Contour 10 m"),
    "contour_medium": ("Courbe 50 m", "Höhenkurve 50 m", "Curva di livello 50 m", "Contour 50 m"),
    "contour_major": ("Courbe 100 m", "Höhenkurve 100 m", "Curva di livello 100 m", "Contour 100 m"),
    "stream": ("Ruisseau", "Bach", "Ruscello", "Stream"),
    "river": ("Rivière", "Fluss", "Fiume", "River"),
    "road_major": ("Route principale", "Hauptstrasse", "Strada principale", "Main road"),
    "road": ("Route", "Strasse", "Strada", "Road"),
    "track": ("Chemin carrossable", "Fahrweg", "Strada carrozzabile", "Track"),
    "path": ("Sentier", "Pfad", "Sentiero", "Path"),
    "hike_t1": ("Chemin de randonnée", "Wanderweg", "Sentiero escursionistico", "Hiking trail"),
    "hike_t2": ("Chemin de montagne", "Bergwanderweg", "Sentiero di montagna", "Mountain trail"),
    "hike_t3": ("Chemin alpin", "Alpinwanderweg", "Sentiero alpino", "Alpine trail"),
    "hike_gr": ("Sentier GR", "Fernwanderweg GR", "Sentiero GR", "GR long-distance trail"),
    "hike_pr": ("Itinéraire balisé (FR)", "Markierter Wanderweg (FR)", "Itinerario segnalato (FR)", "Marked trail (FR)"),
    "rail": ("Chemin de fer", "Eisenbahn", "Ferrovia", "Railway"),
    "aerialway": ("Téléphérique / téléski", "Seilbahn / Skilift", "Funivia / sciovia", "Aerialway"),
    "powerline": ("Ligne électrique", "Stromleitung", "Linea elettrica", "Power line"),
    "peak_major": ("Sommet principal", "Hauptgipfel", "Vetta principale", "Main summit"),
    "peak": ("Sommet", "Gipfel", "Vetta", "Summit"),
    "pass": ("Col", "Pass", "Passo", "Pass"),
    "hut": ("Cabane", "Hütte", "Capanna", "Hut"),
    "settlement": ("Localité", "Ortschaft", "Località", "Locality"),
    "hamlet": ("Hameau", "Weiler", "Frazione", "Hamlet"),
    "locality": ("Lieu-dit", "Flurname", "Toponimo", "Place name"),
    "slope_30": ("Pente 30-35°", "Hangneigung 30-35°", "Pendenza 30-35°", "Slope 30-35°"),
    "slope_35": ("Pente 35-40°", "Hangneigung 35-40°", "Pendenza 35-40°", "Slope 35-40°"),
    "slope_40": ("Pente 40-45°", "Hangneigung 40-45°", "Pendenza 40-45°", "Slope 40-45°"),
    "slope_45": ("Pente > 45°", "Hangneigung > 45°", "Pendenza > 45°", "Slope > 45°"),
    "wildlife_binding": ("Zone faune (obligatoire)", "Wildschutzgebiet (verbindlich)", "Zona fauna (vincolante)", "Wildlife zone (binding)"),
    "wildlife_advised": ("Zone faune (recommandée)", "Wildschutzgebiet (empfohlen)", "Zona fauna (raccomandata)", "Wildlife zone (advised)"),
    "wildlife_edge_binding": ("Limite zone faune", "Grenze Wildschutzgebiet", "Limite zona fauna", "Wildlife zone boundary"),
    "wildlife_edge_advised": ("Limite zone faune (rec.)", "Grenze Wildschutzgebiet (empf.)", "Limite zona fauna (racc.)", "Wildlife zone boundary (advised)"),
    "wildlife_route": ("Itinéraire autorisé (zone faune)", "Erlaubte Route (Wildschutz)", "Itinerario autorizzato (fauna)", "Allowed route (wildlife zone)"),
    "nature_reserve": ("Réserve / protection (hors CH)", "Schutzgebiet (ausser CH)", "Riserva / protezione (fuori CH)", "Nature reserve (outside CH)"),
    "nature_reserve_edge": ("Limite réserve (hors CH)", "Grenze Schutzgebiet (ausser CH)", "Limite riserva (fuori CH)", "Nature reserve boundary (outside CH)"),
    "ski_osm": ("Itinéraire ski OpenStreetMap", "Skitour OpenStreetMap", "Itinerario sci OpenStreetMap", "OpenStreetMap ski route"),
    "ski_c2c": ("Itinéraire ski Camptocamp", "Skitour Camptocamp", "Itinerario sci Camptocamp", "Camptocamp ski route"),
    "ski_c2c_point": ("Course ski Camptocamp", "Skitour Camptocamp (Punkt)", "Gita sci Camptocamp", "Camptocamp ski tour"),
    "ski_route_label": ("Itinéraire ski", "Skitour", "Itinerario sci", "Ski route"),
    "ski": ("Itinéraire ski", "Skitour", "Itinerario sci", "Ski route"),
    "ski_foot": ("Ski : à pied", "Skitour: zu Fuss", "Sci: a piedi", "Ski: on foot"),
    "ski_caution": ("Ski : prudence accrue", "Skitour: erhöhte Vorsicht", "Sci: maggiore prudenza", "Ski: increased caution"),
    "ski_up": ("Ski : sens montée", "Skitour: Aufstieg", "Sci: salita", "Ski: uphill"),
    "ski_down": ("Ski : sens descente", "Skitour: Abfahrt", "Sci: discesa", "Ski: downhill"),
    "snowshoe": ("Itinéraire raquettes", "Schneeschuhroute", "Itinerario racchette", "Snowshoe route"),
    "snowshoe_route_label": ("Itinéraire raquettes", "Schneeschuhroute", "Itinerario racchette",
                             "Snowshoe route"),
}


def _strings(key: str, lang: str):
    labels = dict(zip(LANGS, LABELS[key]))
    out = [f"String=0x00,{labels[lang]}"]   # default when the device language is not listed
    out += [f"String=0x{code:02x},{labels[l]}" for l, code in GARMIN_LANG.items()]
    return out


# --- Generation ---------------------------------------------------------------------

def _rule(c: Cat):
    action = f" {{name '{c.name}'}}" if c.name else ""
    return f"k={c.key}{action} [0x{c.type:x} resolution {c.res}]\n"


def write_style(map_key: str, out_dir: Path, levels: str):
    cats = MAPS[map_key]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "version").write_text("0\n")
    (out_dir / "info").write_text(f"version: 1\nsummary: Swisstopo {map_key}\n")
    (out_dir / "options").write_text(f"levels = {levels}\n")
    for kind, fname in (("point", "points"), ("line", "lines"), ("polygon", "polygons")):
        (out_dir / fname).write_text("".join(_rule(c) for c in cats if c.kind == kind))


def write_typ(map_key: str, path: Path, family_id: int, lang: str):
    cats = MAPS[map_key]
    out = ["; -*- coding: utf-8 -*-", "[_id]", f"FID={family_id}", "ProductCode=1", "CodePage=1252", "[end]", "",
           "[_drawOrder]"]
    out += [f"Type=0x{c.type:02x},{c.order}" for c in cats if c.kind == "polygon"]
    out += ["[end]", ""]
    for c in cats:
        out += [f"[_{c.kind}]", f"Type=0x{c.type:02x}"] + _strings(c.key, lang)
        if c.name is None and c.kind != "point":
            out.append("FontStyle=NoLabel")
        out += c.extra + c.xpm + ["[end]", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
