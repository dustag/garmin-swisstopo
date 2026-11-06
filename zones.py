"""Selectable zones of the configuration window (gui.py): simplified outlines and names.

    python zones.py      # regenerate zones.json from the official boundaries

zones.json is kept in the repository, so that the window starts offline and fast.
Coordinates are LV95 metres, rounded to 10 m; outlines are simplified to ~150 m,
which is plenty to pick a zone but must not be used to cut the map data.

The Pyrenees are drawn as an inset next to the Alps: their zones carry an "offset"
(LV95 metres) that the window adds when drawing, the outlines keeping their true place.
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
# Departments along the Swiss border, Savoie for the Alps south of Haute-Savoie, and the Pyrenees
DEPT_NAMES = {
    "01": ("Ain",) * 4,
    "25": ("Doubs",) * 4,
    "39": ("Jura",) * 4,
    "68": ("Haut-Rhin", "Haut-Rhin", "Alto Reno", "Haut-Rhin"),
    "73": ("Savoie", "Savoyen", "Savoia", "Savoie"),
    "74": ("Haute-Savoie", "Hochsavoyen", "Alta Savoia", "Haute-Savoie"),
    "64": ("Pyrénées-Atlantiques", "Pyrénées-Atlantiques", "Pirenei Atlantici", "Pyrénées-Atlantiques"),
    "65": ("Hautes-Pyrénées", "Hautes-Pyrénées", "Alti Pirenei", "Hautes-Pyrénées"),
    "31": ("Haute-Garonne", "Haute-Garonne", "Alta Garonna", "Haute-Garonne"),
    "09": ("Ariège",) * 4,
    "66": ("Pyrénées-Orientales", "Pyrénées-Orientales", "Pirenei Orientali", "Pyrénées-Orientales"),
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
AUSTRIA_NAMES = {
    "AT341": ("Bludenz-Bregenzerwald",) * 4,
    "AT342": ("Rheintal-lac de Constance", "Rheintal-Bodenseegebiet", "Valle del Reno-Lago di Costanza",
              "Rhine Valley-Lake Constance"),
    "AT331": ("Ausserfern", "Außerfern", "Ausserfern", "Ausserfern"),
    "AT332": ("Innsbruck",) * 4,
    "AT333": ("Tyrol oriental", "Osttirol", "Tirolo orientale", "East Tyrol"),
    "AT334": ("Oberland tyrolien", "Tiroler Oberland", "Oberland tirolese", "Tyrolean Oberland"),
    "AT335": ("Unterland tyrolien", "Tiroler Unterland", "Unterland tirolese", "Tyrolean Unterland"),
    "AT321": ("Lungau",) * 4,
    "AT322": ("Pinzgau-Pongau",) * 4,
    "AT323": ("Salzbourg et environs", "Salzburg und Umgebung", "Salisburgo e dintorni", "Salzburg and surroundings"),
    "AT211": ("Klagenfurt-Villach",) * 4,
    "AT212": ("Haute-Carinthie", "Oberkärnten", "Alta Carinzia", "Upper Carinthia"),
    "AT213": ("Basse-Carinthie", "Unterkärnten", "Bassa Carinzia", "Lower Carinthia"),
    "AT222": ("Liezen",) * 4,
    "AT223": ("Haute-Styrie orientale", "Östliche Obersteiermark", "Alta Stiria orientale", "Eastern Upper Styria"),
    "AT226": ("Haute-Styrie occidentale", "Westliche Obersteiermark", "Alta Stiria occidentale", "Western Upper Styria"),
    "AT315": ("Traunviertel",) * 4,
    "AT121": ("Mostviertel-Eisenwurzen",) * 4,
    "AT122": ("Basse-Autriche sud", "Niederösterreich-Süd", "Bassa Austria meridionale", "Southern Lower Austria"),
}
GERMANY_NAMES = {
    "DE27E": ("Oberallgäu",) * 4,
    "DE27A": ("Lindau (lac de Constance)", "Lindau (Bodensee)", "Lindau (Lago di Costanza)", "Lindau (Lake Constance)"),
    "DE273": ("Kempten (Allgäu)",) * 4,
}
SPAIN_NAMES = {
    "ES220": ("Navarre", "Navarra", "Navarra", "Navarre"),
    "ES241": ("Huesca",) * 4,
    "ES513": ("Lérida", "Lleida", "Lleida", "Lleida"),
    "ES512": ("Gérone", "Girona", "Girona", "Girona"),
}
ANDORRA_NAMES = {"AD": ("Andorre", "Andorra", "Andorra", "Andorra")}
NAMES = {"ch": CANTON_NAMES, "fr": DEPT_NAMES, "it": ITALY_NAMES, "at": AUSTRIA_NAMES, "de": GERMANY_NAMES,
         "es": SPAIN_NAMES, "ad": ANDORRA_NAMES}
NAME_LANGS = ("fr", "de", "it", "en")
# Zones drawn in the Pyrenees inset
PYRENEES = {("fr", c) for c in ("64", "65", "31", "09", "66")} | {("es", c) for c in SPAIN_NAMES} | {("ad", "AD")}
INSET_GAP = 40_000  # m between the Alps and the inset


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
    import countries   # terrain and download modules: not needed by the window
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
    for country, names in (("at", AUSTRIA_NAMES), ("de", GERMANY_NAMES), ("es", SPAIN_NAMES), ("ad", ANDORRA_NAMES)):
        for code in names:
            print(f"zone {code}")
            zones.append(_zone(country, code, countries.Zone(country, code).outline()))
    # Pyrenees inset: below the west of the Alps
    inset = [z for z in zones if (z["country"], z["code"]) in PYRENEES]
    alps = [z for z in zones if (z["country"], z["code"]) not in PYRENEES]
    x0, y1 = _bounds(inset)[0], _bounds(inset)[3]
    ax0, ay0 = _bounds(alps)[0], _bounds(alps)[1]
    offset = [round(ax0 - x0, -3), round(ay0 - INSET_GAP - y1, -3)]
    for z in inset:
        z["offset"] = offset
    ZONES_FILE.write_text(json.dumps(zones, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(zones)} zones -> {ZONES_FILE} ({ZONES_FILE.stat().st_size / 1e3:.0f} kB)")


def _bounds(zone_list):
    xy = [pt for z in zone_list for p in z["polygons"] for pt in p[0]]
    xs, ys = [x for x, _ in xy], [y for _, y in xy]
    return min(xs), min(ys), max(xs), max(ys)


def load() -> list[dict]:
    return json.loads(ZONES_FILE.read_text(encoding="utf-8"))


def name(zone: dict, lang: str) -> str:
    return NAMES[zone["country"]][zone["code"]][NAME_LANGS.index(lang)]


if __name__ == "__main__":
    make()
