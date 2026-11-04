"""Italian data (per zone: a province, or the Piedmont side of the Gran Paradiso):
download and conversion to the map categories.

Sources:
- OpenStreetMap (Geofabrik extracts), licence ODbL: Italy has no national open
  topographic database comparable to swissTLM3D or BD TOPO;
- TINITALY 1.1 (INGV), 10 m terrain model, licence CC BY 4.0;
- Camptocamp ski touring routes, licence CC BY-SA 3.0.

Switzerland and the French departments have priority: Italian data only fills the
part of a tile that lies in the zone, outside Switzerland and the French departments.
"""
import shutil
import urllib.error
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import rasterio
import shapely
from pyproj import Transformer
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject

import config
import coverage
import france

UTM32, LV95 = 32632, 2056
_LV95_TO_UTM = Transformer.from_crs(LV95, UTM32, always_xy=True)
_LV95_TO_WGS84 = Transformer.from_crs(LV95, 4326, always_xy=True)
# ISTAT outlines are generalised: zones are widened so that no gap is left along the
# border, the part beyond it being removed by Switzerland and France's priority.
ZONE_MARGIN = 1000  # m
# Geofabrik extract per ISTAT region code
EXTRACTS = {1: "nord-ovest", 2: "nord-ovest", 3: "nord-ovest", 7: "nord-ovest",
            4: "nord-est", 5: "nord-est", 6: "nord-est", 8: "nord-est"}
TINITALY_TILE = 50_000  # m, UTM 32


def zone_dir(code) -> Path:
    return config.ITALY_DIR / code


def is_ready(code) -> bool:
    return (zone_dir(code) / "ready").exists()


def zone_area(code):
    return coverage.italy_zone(code).buffer(ZONE_MARGIN)


def _to(transformer, geom):
    return shapely.transform(geom, lambda xy: np.column_stack(transformer.transform(xy[:, 0], xy[:, 1])))


# --- Download: terrain ---------------------------------------------------------------------

def download_tinitaly(codes, fetch):
    """TINITALY 10 m, reprojected to LV95 5 m files of 1 km2 (same layout as swissALTI3D)."""
    todo = [c for c in codes if not (zone_dir(c) / "tinitaly.done").exists()]
    if not todo:
        return
    area = shapely.union_all([zone_area(c) for c in todo])
    shapely.prepare(area)
    e0, n0, e1, n1 = (int(v // 1000) for v in area.bounds)
    cells = [(e, n) for e in range(e0, e1 + 1) for n in range(n0, n1 + 1)
             if not (config.ALTI_IT_DIR / f"{e}-{n}.tif").exists()
             and area.intersects(shapely.box(e * 1000, n * 1000, e * 1000 + 1000, n * 1000 + 1000))]

    # 50 km source tiles, named after their south-west corner in UTM 32: w + N + E in 10 km
    src_dir = config.ITALY_DIR / "tinitaly"
    utm_area = _to(_LV95_TO_UTM, area)
    x0, y0, x1, y1 = utm_area.bounds
    sources = []
    for x in range(int(x0 // TINITALY_TILE) * TINITALY_TILE, int(x1), TINITALY_TILE):
        for y in range(int(y0 // TINITALY_TILE) * TINITALY_TILE, int(y1), TINITALY_TILE):
            if not cells or not utm_area.intersects(shapely.box(x, y, x + TINITALY_TILE, y + TINITALY_TILE)):
                continue
            name = f"w{y // 10_000:03d}{x // 10_000:02d}_s10"
            tif = src_dir / f"{name}.tif"
            if not tif.exists():
                try:
                    archive = fetch(f"{config.TINITALY}/{name}/{name}.zip", src_dir / f"{name}.zip", quiet=True)
                except urllib.error.HTTPError as e:
                    if e.code == 404:   # no tile there (sea, or outside Italy)
                        continue
                    raise
                with zipfile.ZipFile(archive) as z, z.open(f"{name}/{name}.tif") as src, open(tif, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                archive.unlink()
            sources.append(rasterio.open(tif))
    if cells:
        print(f"  TINITALY: {len(sources)} tiles, {len(cells)} km2 to convert")

    config.ALTI_IT_DIR.mkdir(parents=True, exist_ok=True)
    for i, (e, n) in enumerate(cells, 1):
        xs, ys = _LV95_TO_UTM.transform([e * 1000, e * 1000 + 1000] * 2, [n * 1000] * 2 + [n * 1000 + 1000] * 2)
        cell_utm = shapely.box(min(xs), min(ys), max(xs), max(ys))
        dst_transform = from_origin(e * 1000, n * 1000 + 1000, 5, 5)
        out = np.full((200, 200), -9999, "float32")
        for src in sources:
            if not cell_utm.intersects(shapely.box(*src.bounds)):
                continue
            part = np.full((200, 200), -9999, "float32")
            reproject(rasterio.band(src, 1), part, src_nodata=src.nodata, dst_transform=dst_transform,
                      dst_crs=f"EPSG:{LV95}", dst_nodata=-9999, resampling=Resampling.bilinear)
            out = np.where(out > -1000, out, part)
        if (out > -1000).any():
            with rasterio.open(config.ALTI_IT_DIR / f"{e}-{n}.tif", "w", driver="GTiff", width=200, height=200,
                               count=1, dtype="float32", crs=f"EPSG:{LV95}", transform=dst_transform,
                               nodata=-9999, compress="deflate", predictor=3) as w:
                w.write(out, 1)
        if i % 500 == 0 or i == len(cells):
            print(f"\r  TINITALY: {i} / {len(cells)} km2", end="" if i < len(cells) else "\n", flush=True)
    for src in sources:
        src.close()
    shutil.rmtree(src_dir, ignore_errors=True)
    for c in todo:
        (zone_dir(c) / "tinitaly.done").touch()


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
    path = config.ITALY_DIR / "osmconf.ini"
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
                   "other_tags LIKE '%\"power\"=>\"line\"%'"]), mask)
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
    out["ref"] = _tag(df, "ref")   # CAI trail numbers
    return out.assign(geometry=df.geometry)[k.notna()]


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


def download_osm(codes, fetch):
    """Map objects from the Geofabrik extracts, classified and saved per zone in LV95.

    Each extract is read once for all the zones it contains, then deleted.
    """
    todo = [c for c in codes if not (zone_dir(c) / "osm.gpkg").exists()]
    by_extract = {}
    for c in todo:
        region = coverage.italy_zone_code(c, "region")
        if region not in EXTRACTS:
            raise ValueError(f"Italian zone {c}: no OpenStreetMap extract configured for ISTAT region {region}")
        by_extract.setdefault(EXTRACTS[region], []).append(c)
    for name, zones in by_extract.items():
        pbf = fetch(f"{config.GEOFABRIK}/{name}-latest.osm.pbf", config.ITALY_DIR / f"{name}.osm.pbf")
        areas = {c: zone_area(c) for c in zones}
        mask = _to(_LV95_TO_WGS84, shapely.union_all(list(areas.values())).simplify(200))
        print(f"  OpenStreetMap {name}: reading {', '.join(zones)} (several minutes)")
        polygons, hut_points = _osm_areas(pbf, mask)
        layers = {"areas": polygons, "lines": _osm_lines(pbf, mask),
                  "points": pd.concat([_osm_points(pbf, mask), hut_points], ignore_index=True)}
        layers = {k: gpd.GeoDataFrame(v, geometry="geometry", crs=4326).to_crs(LV95) for k, v in layers.items()}
        for c, area in areas.items():
            shapely.prepare(area)
            dest = zone_dir(c) / "osm.gpkg"
            tmp = dest.with_suffix(".tmp.gpkg")
            tmp.unlink(missing_ok=True)
            counts = []
            for layer, df in layers.items():
                df = df[shapely.intersects(area, df.geometry.values)]
                pyogrio.write_dataframe(df, tmp, layer=layer)
                counts.append(f"{len(df)} {layer}")
            tmp.replace(dest)
            print(f"  OpenStreetMap {c}: {', '.join(counts)}")
        pbf.unlink()


def download_zones(codes, fetch):
    download_tinitaly(codes, fetch)
    download_osm(codes, fetch)
    for c in codes:
        france.download_camptocamp(zone_dir(c), zone_area(c), c)
        (zone_dir(c) / "ready").touch()


# --- Tile content ------------------------------------------------------------------------

AREA_KEYS = {"forest", "scrub", "rock", "scree", "glacier", "wetland", "lake", "river_area", "building"}
ROAD_KEYS = {"road_major", "road"}
TRAIL_KEYS = {"path", "track", "hike_t1", "hike_t2", "hike_t3"}


def label(row):
    """Name in the label language when the local name is bilingual (South Tyrol, Aosta Valley)."""
    name = row.name if isinstance(row.name, str) else None
    local = getattr(row, f"name_{config.LANG}", None)
    if name and isinstance(local, str) and (" - " in name or " / " in name):
        return local
    return name


def zone_tiles(ctx, codes, foreign):
    """ItalianTile per zone with data in the tile; foreign = Switzerland and the French
    departments, which keep priority. Zones are given disjoint parts of the tile."""
    taken, out = foreign, []
    for c in codes:
        it = ItalianTile(ctx, c, taken, foreign)
        if not it.empty:
            out.append(it)
            taken = shapely.union(taken, it.region)
    return out


class ItalianTile:
    """Reads one zone's data for one tile, limited to its Italian part."""

    def __init__(self, ctx, code, taken, foreign):
        self.ctx, self.code = ctx, code
        box = shapely.box(*ctx.bounds)
        self.region = shapely.make_valid(shapely.difference(
            shapely.intersection(shapely.make_valid(zone_area(code)), box), taken))
        self.foreign = foreign
        self.gpkg = zone_dir(code) / "osm.gpkg"

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
        """Point belongs to this tile's Italian part, away from the Swiss and French borders
        (whose summits and passes are named by swisstopo or IGN)."""
        return (self.ctx.owns(point) and self.region.contains(point)
                and (self.foreign.is_empty or shapely.distance(point, self.foreign) > 150))


def write_base(it: ItalianTile, osm, dem):
    clip = it.clip
    osm.add(it.region, {"k": "land"})
    for row in it.read("areas").itertuples():
        if row.k in AREA_KEYS:
            osm.add(clip(row.geometry), {"k": row.k, "name": label(row) if row.k in ("lake", "glacier") else None})
    for row in it.read("lines").itertuples():
        if row.k in ROAD_KEYS or row.k in ("stream", "aerialway"):
            name = label(row)
        elif row.k in TRAIL_KEYS:
            name = row.ref if isinstance(row.ref, str) else None
        else:
            name = None
        osm.add(clip(row.geometry), {"k": row.k, "name": name})
    for row in it.read("points").itertuples():
        g, name = row.geometry, label(row)
        if not name or not it.owns(g):
            continue
        if row.k in ("peak", "peak_major", "pass"):
            ele = row.ele if row.ele == row.ele else (dem.sample([g.x], [g.y], raw=True)[0] if dem.ok else np.nan)
            name = f"{name} {ele:.0f}" if ele == ele else name
        osm.add(g, {"k": row.k, "name": name})


def write_winter(it: ItalianTile, osm):
    clip = it.clip
    for row in it.read("areas").itertuples():
        if row.k == "nature_reserve":
            g = clip(row.geometry)
            osm.add(g, {"k": "nature_reserve", "name": label(row)})
            osm.add(shapely.boundary(g), {"k": "nature_reserve_edge"})
    df = it.read("routes", path=zone_dir(it.code) / "c2c_ski.gpkg")
    for g, name in zip(df.geometry, df.label):
        if "Point" in g.geom_type:
            if it.owns(g):
                osm.add(g, {"k": "ski_c2c_point", "name": name})
        else:
            osm.add(clip(g), {"k": "ski_c2c", "name": name})
