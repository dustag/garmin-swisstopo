"""Cycling and mountain bike routes, for the cycling overlay (map "velo").

- Switzerland and Liechtenstein: SwitzerlandMobility (Veloland, Mountainbikeland, FEDRO /
  SchweizMobil and the cantons, open government data): the routes with their network level
  and, for mountain bikes, their difficulty, and the single trails.
- Elsewhere (French departments and the zones mapped from OpenStreetMap): the bicycle and
  mtb route relations of OpenStreetMap, read from the Geofabrik extracts and saved per
  department or zone (osm_cycle.gpkg).

Switzerland keeps priority: the OpenStreetMap routes only fill the parts of a tile that the
French departments and the zones fill in the base map.
"""
from pathlib import Path

import geopandas as gpd
import pyogrio
import shapely

import config
import coverage
import osmzone

VELO_DIR = config.DOWNLOAD_DIR / "velo"
LV95 = 2056
# Geofabrik extract of each French department (former regions)
FRANCE_EXTRACTS = {
    **dict.fromkeys(["01", "26", "38", "73", "74"], "europe/france/rhone-alpes"),
    **dict.fromkeys(["04", "05", "06", "83", "84"], "europe/france/provence-alpes-cote-d-azur"),
    **dict.fromkeys(["25", "39"], "europe/france/franche-comte"),
    "64": "europe/france/aquitaine",
    **dict.fromkeys(["31", "09", "65"], "europe/france/midi-pyrenees"),
    "66": "europe/france/languedoc-roussillon",
}
SWISS_LEVELS = {"national": "velo_national", "regional": "velo_regional", "local": "velo_local"}
SWISS_MTB = {"easy": "mtb_easy", "medium": "mtb_medium", "difficult": "mtb_difficult"}
OSM_LEVELS = {"icn": "velo_national", "ncn": "velo_national", "rcn": "velo_regional", "lcn": "velo_local"}


def swiss_path(name) -> Path:
    return VELO_DIR / Path(config.VELO_SOURCES[name]).name


def osm_path(d: Path) -> Path:
    return d / "osm_cycle.gpkg"


# --- Download ----------------------------------------------------------------------------

def download_swiss(fetch):
    for name, url in config.VELO_SOURCES.items():
        fetch(url, swiss_path(name))


def _mtb_key(scale):
    """mtb:scale (0 to 6) -> difficulty."""
    try:
        scale = int(str(scale)[0])
    except (TypeError, ValueError):
        return "mtb_medium"
    return "mtb_easy" if scale <= 1 else "mtb_medium" if scale == 2 else "mtb_difficult"


def _routes(pbf, mask):
    """Bicycle and mtb route relations of an extract, in WGS84: k, name, geometry."""
    df = osmzone._read(pbf, "multilinestrings", ["name"],
                       lambda f: "other_tags LIKE '%\"route\"=>\"bicycle\"%' "
                                 "OR other_tags LIKE '%\"route\"=>\"mtb\"%'", mask)
    route = osmzone._tag(df, "route")
    k = osmzone._tag(df, "network").map(OSM_LEVELS).fillna("velo_local")
    k = k.mask(route == "mtb", osmzone._tag(df, "mtb:scale").map(_mtb_key).fillna("mtb_medium"))
    name = osmzone._tag(df, "ref").fillna(osmzone._tag(df, "name"))
    keep = route.isin(["bicycle", "mtb"])
    return gpd.GeoDataFrame({"k": k[keep], "name": name[keep]}, geometry=df.geometry[keep], crs=4326)


def download_osm(areas, fetch):
    """OpenStreetMap routes of the areas still without them. areas: (directory, outline in
    LV95, Geofabrik extract, label). Each extract is read once, then deleted."""
    by_extract = {}
    for d, outline, extract, what in areas:
        if not osm_path(d).exists():
            by_extract.setdefault(extract, []).append((d, outline, what))
    for extract, group in by_extract.items():
        name = extract.rsplit("/", 1)[-1]
        pbf = fetch(osmzone.extract_url(extract), config.DOWNLOAD_DIR / "osm" / f"{name}.osm.pbf")
        area = shapely.union_all([o.buffer(1000) for _, o, _ in group])
        print(f"  OpenStreetMap {name}: cycling routes of {', '.join(w for _, _, w in group)}")
        routes = _routes(pbf, osmzone._to_wgs84(area.simplify(200))).to_crs(LV95)
        for d, outline, what in group:
            part = outline.buffer(1000)
            df = routes[shapely.intersects(part, routes.geometry.values)].copy()
            df["geometry"] = shapely.intersection(df.geometry.values, part)
            d.mkdir(parents=True, exist_ok=True)
            pyogrio.write_dataframe(df, osm_path(d), layer="routes")
            print(f"  OpenStreetMap {what}: {len(df)} cycling routes")
        pbf.unlink()


# --- Tile content ----------------------------------------------------------------------------

def write_swiss(ctx, osm):
    """SwitzerlandMobility routes of the tile, limited to Switzerland and Liechtenstein."""
    ch = shapely.intersection(shapely.make_valid(coverage.switzerland()), shapely.box(*ctx.bounds))

    def clip(g):
        return shapely.intersection(shapely.force_2d(g), ch)

    if swiss_path("veloland").exists():
        df = pyogrio.read_dataframe(swiss_path("veloland"), layer="Route", columns=["NrR", "Typ_TR"],
                                    bbox=ctx.bounds)
        for g, nr, level in zip(df.geometry, df.NrR, df.Typ_TR):
            osm.add(clip(g), {"k": SWISS_LEVELS.get(level, "velo_local"), "name": nr})
    if swiss_path("mountainbikeland").exists():
        path = swiss_path("mountainbikeland")
        df = pyogrio.read_dataframe(path, layer="Route", columns=["NrR", "TechnikR"], bbox=ctx.bounds)
        for g, nr, technique in zip(df.geometry, df.NrR, df.TechnikR):
            osm.add(clip(g), {"k": SWISS_MTB.get(technique, "mtb_medium"), "name": nr})
        df = pyogrio.read_dataframe(path, layer="Weg", columns=["IsSTrail"], bbox=ctx.bounds)
        for g in df.geometry[df.IsSTrail == 1]:
            osm.add(clip(g), {"k": "mtb_singletrail"})


def write_osm(part, d: Path, osm):
    """OpenStreetMap routes of a department or zone, limited to its part of the tile
    (part: a FrenchTile or a ZoneTile)."""
    if not osm_path(d).exists():
        return
    df = pyogrio.read_dataframe(osm_path(d), layer="routes", bbox=part.ctx.bounds)
    for g, k, name in zip(df.geometry, df.k, df.name):
        osm.add(part.clip(g), {"k": k, "name": name})


def sources(depts, zones, france_dir):
    """What the cycling overlay of a tile is made of, for its cache key."""
    return ([n for n in config.VELO_SOURCES if swiss_path(n).exists()]
            + [f"fr{c}" for c in depts if osm_path(france_dir(c)).exists()]
            + [z.code for z in zones if osm_path(z.dir).exists()])
