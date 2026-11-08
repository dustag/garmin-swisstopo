"""Selectable zones of the configuration window (gui.py): simplified outlines and names,
and a coarse shaded relief drawn under them.

    python zones.py            # regenerate zones.json and the relief from the official data
    python zones.py --relief   # regenerate only the relief (relief.json, relief_*.png)

zones.json and the relief are kept in the repository, so that the window starts offline
and fast. Coordinates are LV95 metres, rounded to 10 m; outlines are simplified to ~150 m,
which is plenty to pick a zone but must not be used to cut the map data.

The Pyrenees are drawn as an inset next to the Alps: their zones carry an "offset"
(LV95 metres) that the window adds when drawing, the outlines keeping their true place.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import shapely
from shapely.ops import polylabel

import config
import coverage

REPO = Path(__file__).resolve().parent
ZONES_FILE = REPO / "zones.json"
RELIEF_FILE = REPO / "relief.json"
SIMPLIFY = 150  # m
# Shaded relief: Copernicus GLO-90, read from its overviews at about RELIEF_RES
COPERNICUS_90 = "https://copernicus-dem-90m.s3.amazonaws.com"
RELIEF_RES = 500   # m per pixel
RELIEF_MARGIN = 20_000  # m around the zones

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
    "LI": ("Liechtenstein",) * 4,
}
# Departments of the Jura, the Alps and the Pyrenees
DEPT_NAMES = {
    "01": ("Ain",) * 4,
    "25": ("Doubs",) * 4,
    "39": ("Jura",) * 4,
    "68": ("Haut-Rhin", "Haut-Rhin", "Alto Reno", "Haut-Rhin"),
    "73": ("Savoie", "Savoyen", "Savoia", "Savoie"),
    "74": ("Haute-Savoie", "Hochsavoyen", "Alta Savoia", "Haute-Savoie"),
    "38": ("Isère",) * 4,
    "05": ("Hautes-Alpes", "Hautes-Alpes", "Alte Alpi", "Hautes-Alpes"),
    "04": ("Alpes-de-Haute-Provence", "Alpes-de-Haute-Provence", "Alpi dell'Alta Provenza", "Alpes-de-Haute-Provence"),
    "06": ("Alpes-Maritimes", "Alpes-Maritimes", "Alpi Marittime", "Alpes-Maritimes"),
    "26": ("Drôme",) * 4,
    "83": ("Var",) * 4,
    "84": ("Vaucluse",) * 4,
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
    "TO": ("Turin", "Turin", "Torino", "Turin"),
    "CN": ("Coni", "Cuneo", "Cuneo", "Cuneo"),
    "BI": ("Biella",) * 4,
    "VC": ("Verceil", "Vercelli", "Vercelli", "Vercelli"),
    "NO": ("Novare", "Novara", "Novara", "Novara"),
    "IM": ("Imperia",) * 4,
    "SV": ("Savone", "Savona", "Savona", "Savona"),
    "LC": ("Lecco",) * 4,
    "BG": ("Bergame", "Bergamo", "Bergamo", "Bergamo"),
    "BS": ("Brescia",) * 4,
    "TN": ("Trentin", "Trentino", "Trentino", "Trentino"),
    "VR": ("Vérone", "Verona", "Verona", "Verona"),
    "VI": ("Vicence", "Vicenza", "Vicenza", "Vicenza"),
    "BL": ("Bellune", "Belluno", "Belluno", "Belluno"),
    "TV": ("Trévise", "Treviso", "Treviso", "Treviso"),
    "PN": ("Pordenone",) * 4,
    "UD": ("Udine",) * 4,
    "GO": ("Gorizia", "Görz", "Gorizia", "Gorizia"),
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
    "AT123": ("Sankt Pölten",) * 4,
    "AT126": ("Environs de Vienne nord", "Wiener Umland/Nordteil", "Dintorni di Vienna nord", "Vienna surroundings north"),
    "AT127": ("Environs de Vienne sud", "Wiener Umland/Südteil", "Dintorni di Vienna sud", "Vienna surroundings south"),
    "AT111": ("Burgenland central", "Mittelburgenland", "Burgenland centrale", "Central Burgenland"),
    "AT112": ("Burgenland nord", "Nordburgenland", "Burgenland settentrionale", "Northern Burgenland"),
    "AT113": ("Burgenland sud", "Südburgenland", "Burgenland meridionale", "Southern Burgenland"),
    "AT221": ("Graz",) * 4,
    "AT224": ("Styrie orientale", "Oststeiermark", "Stiria orientale", "Eastern Styria"),
    "AT225": ("Styrie occidentale et méridionale", "West- und Südsteiermark", "Stiria occidentale e meridionale",
              "Western and Southern Styria"),
    "AT314": ("Steyr-Kirchdorf",) * 4,
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
PYRENEES = {(country, code) for country, codes in config.REGIONS["pyrenees"].items() for code in codes}
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
    for code in CANTON_NAMES:
        print(f"canton {code}")
        zones.append(_zone("ch", code, coverage.canton(code)))
    for code in DEPT_NAMES:
        print(f"department {code}")
        zones.append(_zone("fr", code, coverage.dept_outline(code)))
    for code in ITALY_NAMES:
        print(f"Italian zone {code}")
        zones.append(_zone("it", code, countries.Zone("it", code).outline()))
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
    make_relief(zones)


def make_relief(zones=None):
    """Shaded relief under the Alps and under the Pyrenees inset (relief.json, relief_*.png)."""
    zones = zones or load()
    parts = {"alps": [z for z in zones if "offset" not in z], "pyrenees": [z for z in zones if "offset" in z]}
    meta = []
    for name, part in parts.items():
        if not part:
            continue
        e0, n0, e1, n1 = _bounds(part)
        bounds = [math.floor((e0 - RELIEF_MARGIN) / RELIEF_RES) * RELIEF_RES,
                  math.floor((n0 - RELIEF_MARGIN) / RELIEF_RES) * RELIEF_RES,
                  math.ceil((e1 + RELIEF_MARGIN) / RELIEF_RES) * RELIEF_RES,
                  math.ceil((n1 + RELIEF_MARGIN) / RELIEF_RES) * RELIEF_RES]
        path = REPO / f"relief_{name}.png"
        _shaded_relief(bounds, path)
        meta.append({"file": path.name, "bounds": bounds, "res": RELIEF_RES, "offset": part[0].get("offset", [0, 0])})
        print(f"relief {name} -> {path} ({path.stat().st_size / 1e3:.0f} kB)")
    RELIEF_FILE.write_text(json.dumps(meta), encoding="utf-8")


def _shaded_relief(bounds, path):
    """Shading of an LV95 box as a transparent PNG: shadows in black, lit slopes in white,
    so that it shows on a light or a dark background."""
    import warnings

    import rasterio
    from pyproj import Transformer
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin
    from rasterio.warp import reproject

    e0, n0, e1, n1 = bounds
    width, height = int((e1 - e0) / RELIEF_RES), int((n1 - n0) / RELIEF_RES)
    dst_transform = from_origin(e0, n1, RELIEF_RES, RELIEF_RES)
    z = np.full((height, width), np.nan, "float32")
    xs, ys = np.meshgrid(np.linspace(e0, e1, 20), np.linspace(n0, n1, 20))
    lon, lat = Transformer.from_crs(2056, 4326, always_xy=True).transform(xs.ravel(), ys.ravel())
    for la in range(math.floor(min(lat)), math.floor(max(lat)) + 1):
        for lo in range(math.floor(min(lon)), math.floor(max(lon)) + 1):
            name = (f"Copernicus_DSM_COG_30_{'N' if la >= 0 else 'S'}{abs(la):02d}_00_"
                    f"{'E' if lo >= 0 else 'W'}{abs(lo):03d}_00_DEM")
            try:
                with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"), \
                        rasterio.open(f"/vsicurl/{COPERNICUS_90}/{name}/{name}.tif") as r:
                    # A decimated read uses the overviews: a few hundred kB per tile
                    f = max(1, round(RELIEF_RES / 90 / 2))
                    data = r.read(1, out_shape=(r.height // f, r.width // f), resampling=Resampling.average)
                    src_transform = r.transform * r.transform.scale(r.width / data.shape[1], r.height / data.shape[0])
            except rasterio.errors.RasterioIOError:
                continue   # sea
            part = np.full_like(z, np.nan)
            reproject(data.astype("float32"), part, src_transform=src_transform, src_crs="EPSG:4326",
                      dst_transform=dst_transform, dst_crs="EPSG:2056", dst_nodata=np.nan,
                      resampling=Resampling.bilinear)
            z = np.where(np.isnan(z), part, z)
            print(f"  {name}", flush=True)
    land = ~np.isnan(z) & (np.nan_to_num(z) > 0)
    z = np.nan_to_num(z)
    # Hill shading, light from the north-west, slopes exaggerated for a 500 m grid
    gy, gx = np.gradient(z * 2.5, RELIEF_RES)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = math.radians(315), math.radians(45)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    flat = math.sin(alt)
    rgba = np.zeros((4, height, width), "uint8")
    dark = np.clip((flat - shade) / flat, 0, 1)
    light = np.clip((shade - flat) / (1 - flat), 0, 1)
    rgba[0:3] = np.where(light > 0, 255, 0).astype("uint8")
    rgba[3] = np.where(land, np.clip(dark * 150 + light * 90, 0, 255), 0).astype("uint8")
    with warnings.catch_warnings():   # a plain image: no georeferencing on purpose
        warnings.simplefilter("ignore", rasterio.errors.NotGeoreferencedWarning)
        with rasterio.open(path, "w", driver="PNG", width=width, height=height, count=4, dtype="uint8") as w:
            w.write(rgba)
    path.with_suffix(".png.aux.xml").unlink(missing_ok=True)


def load_relief() -> list[dict]:
    return json.loads(RELIEF_FILE.read_text(encoding="utf-8")) if RELIEF_FILE.exists() else []


def _bounds(zone_list):
    xy = [pt for z in zone_list for p in z["polygons"] for pt in p[0]]
    xs, ys = [x for x, _ in xy], [y for _, y in xy]
    return min(xs), min(ys), max(xs), max(ys)


def load() -> list[dict]:
    return json.loads(ZONES_FILE.read_text(encoding="utf-8"))


def name(zone: dict, lang: str) -> str:
    return NAMES[zone["country"]][zone["code"]][NAME_LANGS.index(lang)]


if __name__ == "__main__":
    make_relief() if "--relief" in sys.argv else make()
