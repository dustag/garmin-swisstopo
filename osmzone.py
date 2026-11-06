"""Countries mapped from OpenStreetMap (Italy, Austria, Bavaria, Spain, Andorra): download
of the zones' data and conversion to the map categories.

A zone (see countries.py) is a province, a NUTS 3 region or a country. For each zone the
Geofabrik extract containing it is read once, its objects classified into the map
categories and saved in LV95 (osm.gpkg), with the Camptocamp ski touring routes.

Switzerland and the French departments have priority, then the countries in the order of
config.OSM_ZONES: a zone only fills the part of a tile that no one before it took.
"""
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely
from pyproj import Transformer

import config
import france

LV95 = 2056
_LV95_TO_WGS84 = Transformer.from_crs(LV95, 4326, always_xy=True)
# Bump when the classification changes: zones extracted before are extracted again
OSM_FORMAT = 2


def _to_wgs84(geom):
    return shapely.transform(geom, lambda xy: np.column_stack(_LV95_TO_WGS84.transform(xy[:, 0], xy[:, 1])))


# --- Download: OpenStreetMap -----------------------------------------------------------------

NATURAL = {"wood": "forest", "scrub": "scrub", "heath": "scrub", "bare_rock": "rock", "scree": "scree",
           "shingle": "scree", "glacier": "glacier", "wetland": "wetland", "water": "lake"}
LANDUSE = {"forest": "forest", "reservoir": "lake", "basin": "lake"}
RIVER_WATER = {"river", "canal", "stream", "oxbow"}
# IUCN classes kept as protected areas (6 and above: sustainable use, Natura 2000...)
PROTECT_CLASSES = {"1", "1a", "1b", "2", "3", "4", "5"}
HIGHWAYS = {
    **dict.fromkeys(["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
                     "secondary", "secondary_link"], "road_major"),
    **dict.fromkeys(["tertiary", "tertiary_link", "unclassified", "residential", "living_street",
                     "service", "road"], "road"),
    "track": "track",
    **dict.fromkeys(["path", "footway", "bridleway", "steps"], "path"),
    "via_ferrata": "hike_t3",
}
# SAC hiking scale -> Swiss hiking categories (yellow, white-red-white, white-blue-white)
SAC_SCALE = {"hiking": "hike_t1", "mountain_hiking": "hike_t2", "demanding_mountain_hiking": "hike_t2",
             "alpine_hiking": "hike_t3", "demanding_alpine_hiking": "hike_t3", "difficult_alpine_hiking": "hike_t3"}
RAILWAYS = {"rail", "narrow_gauge", "light_rail", "funicular"}
AERIALWAYS = {"cable_car", "gondola", "mixed_lift", "chair_lift", "drag_lift", "t-bar", "j-bar", "platter", "rope_tow"}
PLACES = {"city": "settlement", "town": "settlement", "village": "settlement",
          "hamlet": "hamlet", "isolated_dwelling": "hamlet", "locality": "locality"}
HUTS = {"alpine_hut", "wilderness_hut"}
NAME_LANGS = ("fr", "de", "it", "en")


def _tag(df, key):
    """Tag values as a Series: from its own column, or parsed from other_tags."""
    if key in df.columns:
        return df[key]
    return df["other_tags"].str.extract(rf'"{key}"=>"([^"]*)"', expand=False)


def _names(df, out):
    out["name"] = _tag(df, "name")
    for lang in NAME_LANGS:
        out[f"name_{lang}"] = _tag(df, f"name:{lang}")
    return out


def _osm_config():
    """GDAL's OSM driver configuration, keeping the ele tag that it drops by default."""
    path = config.DOWNLOAD_DIR / "osm" / "osmconf.ini"
    path.parent.mkdir(parents=True, exist_ok=True)
    default = (Path(pyogrio.get_gdal_data_path()) / "osmconf.ini").read_text()
    path.write_text(default.replace(",ele,", ","))
    pyogrio.set_gdal_config_options({"OSM_CONFIG_FILE": str(path)})


def _read(pbf, layer, keys, where, mask):
    """Read an OSM layer restricted to mask, keeping the columns that exist among keys."""
    _osm_config()
    fields = set(pyogrio.read_info(pbf, layer=layer)["fields"])
    return pyogrio.read_dataframe(pbf, layer=layer, columns=[k for k in keys if k in fields] + ["other_tags"],
                                  where=where(fields), mask=mask)


def _has(fields, key, cond):
    """SQL condition on a tag, whether it has its own column or sits in other_tags."""
    return f"{key} {cond}" if key in fields else f"other_tags LIKE '%\"{key}\"=>%'"


def _osm_areas(pbf, mask):
    df = _read(pbf, "multipolygons", ["name", "building", "natural", "landuse", "boundary", "leisure", "tourism"],
               lambda f: " OR ".join([
                   _has(f, "building", "IS NOT NULL"),
                   _has(f, "natural", "IN ('" + "','".join(NATURAL) + "')"),
                   _has(f, "landuse", "IN ('" + "','".join(LANDUSE) + "')"),
                   _has(f, "boundary", "IN ('national_park','protected_area')"),
                   _has(f, "leisure", "= 'nature_reserve'"),
                   _has(f, "tourism", "IN ('alpine_hut','wilderness_hut')")]), mask)
    k = _tag(df, "natural").map(NATURAL).fillna(_tag(df, "landuse").map(LANDUSE))
    k = k.mask((k == "lake") & _tag(df, "water").isin(RIVER_WATER), "river_area")
    building = _tag(df, "building")
    k = k.mask(building.notna() & (building != "no"), "building")
    boundary = _tag(df, "boundary")
    reserve = ((boundary == "national_park") | (_tag(df, "leisure") == "nature_reserve")
               | ((boundary == "protected_area") & _tag(df, "protect_class").isin(PROTECT_CLASSES)))
    k = k.mask(reserve, "nature_reserve")
    out = _names(df, pd.DataFrame({"k": k}))
    areas = out.assign(geometry=df.geometry)[k.notna()]
    # Huts mapped as buildings: a point for the label
    huts = _tag(df, "tourism").isin(HUTS)
    hut_points = _names(df[huts], pd.DataFrame({"k": "hut"}, index=df.index[huts]))
    hut_points["geometry"] = df.geometry[huts].representative_point()
    return areas, hut_points


def _osm_lines(pbf, mask):
    df = _read(pbf, "lines", ["name", "highway", "waterway", "aerialway", "railway"],
               lambda f: " OR ".join([
                   _has(f, "highway", "IS NOT NULL"), _has(f, "waterway", "IN ('river','stream')"),
                   _has(f, "aerialway", "IS NOT NULL"), _has(f, "railway", "IS NOT NULL"),
                   "other_tags LIKE '%\"power\"=>\"line\"%'",
                   "other_tags LIKE '%\"piste:type\"=>\"skitour\"%'"]), mask)
    highway = _tag(df, "highway")
    k = highway.map(HIGHWAYS)
    k = k.mask(k.isin(["path", "track"]) & _tag(df, "sac_scale").isin(SAC_SCALE),
               _tag(df, "sac_scale").map(SAC_SCALE))
    k = k.fillna(_tag(df, "waterway").map({"river": "stream", "stream": "stream"}))
    k = k.fillna(_tag(df, "railway").map(dict.fromkeys(RAILWAYS, "rail")))
    k = k.fillna(_tag(df, "aerialway").map(dict.fromkeys(AERIALWAYS, "aerialway")))
    k = k.fillna(_tag(df, "power").map({"line": "powerline"}))
    tunnel = _tag(df, "tunnel")
    k = k.mask(tunnel.notna() & (tunnel != "no"))
    out = _names(df, pd.DataFrame({"k": k}))
    out["ref"] = _tag(df, "ref")   # trail numbers (CAI, Austrian Alpine Club...)
    lines = out.assign(geometry=df.geometry)[k.notna()]
    # Ski touring routes mapped in OpenStreetMap, as ways (own rows: the way may also be a
    # path) or as route relations
    rel = _read(pbf, "multilinestrings", ["name"], lambda f: "other_tags LIKE '%\"piste:type\"=>\"skitour\"%'", mask)
    tours = []
    for d in (df, rel):
        ski = _tag(d, "piste:type") == "skitour"
        t = _names(d[ski], pd.DataFrame({"k": "ski_osm"}, index=d.index[ski]))
        t["name"] = _tag(d[ski], "piste:name").fillna(t["name"])
        tours.append(t.assign(ref=None, geometry=d.geometry[ski]))
    return pd.concat([lines] + tours, ignore_index=True)


def _osm_points(pbf, mask):
    df = _read(pbf, "points", ["name", "place"],
               lambda f: " OR ".join([
                   _has(f, "place", "IN ('" + "','".join(PLACES) + "')"),
                   "other_tags LIKE '%\"natural\"=>\"peak\"%'", "other_tags LIKE '%\"natural\"=>\"saddle\"%'",
                   "other_tags LIKE '%\"mountain_pass\"=>\"yes\"%'",
                   "other_tags LIKE '%\"tourism\"=>\"alpine_hut\"%'",
                   "other_tags LIKE '%\"tourism\"=>\"wilderness_hut\"%'"]), mask)
    natural = _tag(df, "natural")
    # Summits with a Wikipedia article stand out as major ones
    famous = _tag(df, "wikidata").notna() | _tag(df, "wikipedia").notna()
    k = pd.Series(None, index=df.index, dtype=object)
    k = k.mask(natural == "peak", famous.map({True: "peak_major", False: "peak"}))
    k = k.mask((natural == "saddle") | (_tag(df, "mountain_pass") == "yes"), "pass")
    k = k.mask(_tag(df, "tourism").isin(HUTS), "hut")
    k = k.fillna(_tag(df, "place").map(PLACES))
    out = _names(df, pd.DataFrame({"k": k}))
    ele = _tag(df, "ele").str.replace(",", ".").str.extract(r"^\s*(-?\d+(?:\.\d+)?)", expand=False)
    out["ele"] = pd.to_numeric(ele, errors="coerce")
    return out.assign(geometry=df.geometry)[k.notna()]


def osm_format(zone) -> int:
    """Format of the zone's extracted data (1: before the format was recorded)."""
    f = zone.dir / "osm.format"
    return int(f.read_text()) if f.exists() else 1


def osm_ready(zone) -> bool:
    return (zone.dir / "osm.gpkg").exists() and osm_format(zone) == OSM_FORMAT


def download_osm(zones, fetch):
    """Map objects from the Geofabrik extracts, classified and saved per zone in LV95.

    Each extract is read once for all the zones it contains, then deleted.
    """
    by_extract = {}
    for z in zones:
        if not osm_ready(z):
            by_extract.setdefault(z.extract, []).append(z)
    for extract, group in by_extract.items():
        name = extract.rsplit("/", 1)[-1]
        pbf = fetch(f"{config.GEOFABRIK}/{extract}-latest.osm.pbf", config.DOWNLOAD_DIR / "osm" / f"{name}.osm.pbf")
        areas = {z: z.area() for z in group}
        mask = _to_wgs84(shapely.union_all(list(areas.values())).simplify(200))
        print(f"  OpenStreetMap {name}: reading {', '.join(z.code for z in group)} (several minutes)")
        polygons, hut_points = _osm_areas(pbf, mask)
        layers = {"areas": polygons, "lines": _osm_lines(pbf, mask),
                  "points": pd.concat([_osm_points(pbf, mask), hut_points], ignore_index=True)}
        layers = {k: gpd.GeoDataFrame(v, geometry="geometry", crs=4326).to_crs(LV95) for k, v in layers.items()}
        for z, area in areas.items():
            shapely.prepare(area)
            dest = z.dir / "osm.gpkg"
            tmp = dest.with_suffix(".tmp.gpkg")
            tmp.unlink(missing_ok=True)
            counts = []
            for layer, df in layers.items():
                df = df[shapely.intersects(area, df.geometry.values)]
                pyogrio.write_dataframe(df, tmp, layer=layer)
                counts.append(f"{len(df)} {layer}")
            tmp.replace(dest)
            (z.dir / "osm.format").write_text(str(OSM_FORMAT))
            print(f"  OpenStreetMap {z.code}: {', '.join(counts)}")
        pbf.unlink()


def download_zones(zones, fetch):
    """Terrain, OpenStreetMap objects and Camptocamp routes of the zones."""
    by_dem = {}
    for z in zones:
        if not (z.dir / "dem.done").exists():
            by_dem.setdefault(z.dem, []).append(z)
    for dem, group in by_dem.items():
        dem(shapely.union_all([z.area() for z in group]), fetch)
        for z in group:
            z.dir.mkdir(parents=True, exist_ok=True)
            (z.dir / "dem.done").touch()
    download_osm(zones, fetch)
    for z in zones:
        france.download_camptocamp(z.dir, z.area(), z.code)
        (z.dir / "ready").touch()


# --- Tile content ------------------------------------------------------------------------

AREA_KEYS = {"forest", "scrub", "rock", "scree", "glacier", "wetland", "lake", "river_area", "building"}
ROAD_KEYS = {"road_major", "road"}
TRAIL_KEYS = {"path", "track", "hike_t1", "hike_t2", "hike_t3"}


WINTER_LINE_KEYS = {"ski_osm"}


def label(row):
    """Name in the label language when the local name is bilingual (South Tyrol, Aosta Valley, Basque Country...)."""
    name = row.name if isinstance(row.name, str) else None
    local = getattr(row, f"name_{config.LANG}", None)
    if name and isinstance(local, str) and (" - " in name or " / " in name):
        return local
    return name


def zone_tiles(ctx, zones, foreign, neighbours):
    """ZoneTile per zone with data in the tile, in priority order.

    foreign: Switzerland and the French departments, which keep priority. neighbours: the
    outlines of all the OpenStreetMap zones in the tile. A zone is widened beyond its
    generalised outline to leave no gap along Switzerland and France, but not into
    another zone: the extracts barely go past their borders.
    """
    taken, out = foreign, []
    for z in zones:
        # Where outlines from different sources overlap, the first zone in priority order
        # takes the overlap (the later ones find it taken)
        others = shapely.difference(shapely.union_all([g for k, g in neighbours.items() if k != z.key]),
                                    neighbours[z.key])
        t = ZoneTile(ctx, z, shapely.union(taken, others), foreign)
        if not t.empty:
            out.append(t)
            taken = shapely.union(taken, t.region)
    return out


class ZoneTile:
    """Reads one zone's data for one tile, limited to the part of the tile it fills."""

    def __init__(self, ctx, zone, taken, foreign):
        self.ctx, self.zone = ctx, zone
        box = shapely.box(*ctx.bounds)
        self.region = shapely.make_valid(shapely.difference(
            shapely.intersection(shapely.make_valid(zone.area()), box), taken))
        self.foreign = foreign
        self.gpkg = zone.dir / "osm.gpkg"

    @property
    def empty(self):
        return self.region.is_empty or self.region.area < 1

    def read(self, layer, path=None):
        return pyogrio.read_dataframe(path or self.gpkg, layer=layer, bbox=self.ctx.bounds)

    def clip(self, geom):
        if not shapely.is_valid(geom):
            geom = shapely.make_valid(geom)
        return shapely.intersection(geom, self.region)

    def owns(self, point):
        """Point belongs to this part of the tile, away from the Swiss and French borders
        (whose summits and passes are named by swisstopo or IGN)."""
        return (self.ctx.owns(point) and self.region.contains(point)
                and (self.foreign.is_empty or shapely.distance(point, self.foreign) > 150))


def write_base(zt: ZoneTile, osm, dem):
    clip = zt.clip
    osm.add(zt.region, {"k": "land"})
    for row in zt.read("areas").itertuples():
        if row.k in AREA_KEYS:
            osm.add(clip(row.geometry), {"k": row.k, "name": label(row) if row.k in ("lake", "glacier") else None})
    for row in zt.read("lines").itertuples():
        if row.k in WINTER_LINE_KEYS:
            continue
        if row.k in ROAD_KEYS or row.k in ("stream", "aerialway"):
            name = label(row)
        elif row.k in TRAIL_KEYS:
            name = row.ref if isinstance(row.ref, str) else None
        else:
            name = None
        osm.add(clip(row.geometry), {"k": row.k, "name": name})
    for row in zt.read("points").itertuples():
        g, name = row.geometry, label(row)
        if not name or not zt.owns(g):
            continue
        if row.k in ("peak", "peak_major", "pass"):
            ele = row.ele if row.ele == row.ele else (dem.sample([g.x], [g.y], raw=True)[0] if dem.ok else np.nan)
            name = f"{name} {ele:.0f}" if ele == ele else name
        osm.add(g, {"k": row.k, "name": name})


def write_winter(zt: ZoneTile, osm):
    clip = zt.clip
    for row in zt.read("areas").itertuples():
        if row.k == "nature_reserve":
            g = clip(row.geometry)
            osm.add(g, {"k": "nature_reserve", "name": label(row)})
            osm.add(shapely.boundary(g), {"k": "nature_reserve_edge"})
    for row in zt.read("lines").itertuples():
        if row.k in WINTER_LINE_KEYS:
            osm.add(clip(row.geometry), {"k": row.k, "name": label(row)})
    df = zt.read("routes", path=zt.zone.dir / "c2c_ski.gpkg")
    for g, name in zip(df.geometry, df.label):
        if "Point" in g.geom_type:
            if zt.owns(g):
                osm.add(g, {"k": "ski_c2c_point", "name": name})
        else:
            osm.add(clip(g), {"k": "ski_c2c", "name": name})
