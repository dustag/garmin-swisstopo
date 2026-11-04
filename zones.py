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

CANTON_NAMES = {
    "ZH": "Zurich", "BE": "Berne", "LU": "Lucerne", "UR": "Uri", "SZ": "Schwytz", "OW": "Obwald",
    "NW": "Nidwald", "GL": "Glaris", "ZG": "Zoug", "FR": "Fribourg", "SO": "Soleure", "BS": "Bâle-Ville",
    "BL": "Bâle-Campagne", "SH": "Schaffhouse", "AR": "Appenzell Rh.-Ext.", "AI": "Appenzell Rh.-Int.",
    "SG": "Saint-Gall", "GR": "Grisons", "AG": "Argovie", "TG": "Thurgovie", "TI": "Tessin", "VD": "Vaud",
    "VS": "Valais", "NE": "Neuchâtel", "GE": "Genève", "JU": "Jura",
}
# Departments along the Swiss border, and Savoie for the Alps south of Haute-Savoie
DEPT_NAMES = {
    "01": "Ain", "25": "Doubs", "39": "Jura", "68": "Haut-Rhin", "73": "Savoie", "74": "Haute-Savoie",
    "90": "Territoire de Belfort",
}
ITALY_NAMES = {
    "AO": "Vallée d'Aoste", "VB": "Verbano-Cusio-Ossola", "VA": "Varèse", "CO": "Côme", "SO": "Sondrio",
    "BZ": "Bolzano", "GP": "Grand Paradis (Piémont)",
}


def _zone(country, code, name, geom):
    geom = shapely.make_valid(shapely.simplify(geom, SIMPLIFY))
    polys = [p for p in getattr(geom, "geoms", [geom]) if p.geom_type == "Polygon" and p.area > 1e6]
    # Label in the largest part, at the point farthest from its edges
    label = polylabel(max(polys, key=lambda p: p.area), tolerance=200)
    rnd = lambda cs: [[round(x, -1), round(y, -1)] for x, y in cs]
    return {"country": country, "code": code, "name": name, "label": [round(label.x, -1), round(label.y, -1)],
            "area_km2": round(sum(p.area for p in polys) / 1e6),
            "polygons": [[rnd(p.exterior.coords)] + [rnd(r.coords) for r in p.interiors] for p in polys]}


def make():
    zones = []
    for code in config.CANTONS:
        print(f"canton {code}")
        geom = coverage.boundary("ch.swisstopo.swissboundaries3d-kanton-flaeche.fill", "ak", code)
        zones.append(_zone("ch", code, CANTON_NAMES[code], geom))
    for code, name in DEPT_NAMES.items():
        print(f"department {code}")
        zones.append(_zone("fr", code, name, coverage.department(code)))
    for code, name in ITALY_NAMES.items():
        print(f"Italian zone {code}")
        zones.append(_zone("it", code, name, coverage.italy_zone(code)))
    ZONES_FILE.write_text(json.dumps(zones, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(zones)} zones -> {ZONES_FILE} ({ZONES_FILE.stat().st_size / 1e3:.0f} kB)")


def load() -> list[dict]:
    return json.loads(ZONES_FILE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    make()
