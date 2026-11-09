"""Build the Garmin maps (.img) for a coverage.

    python build.py                          # coverage from .env
    python build.py --coverage canton:VS     # area, switzerland, canton:XX, dept:NN, it:XX, at:XX, alpes...
    python build.py --no-dem                 # without hill shading
    python build.py --maps hiver             # only the winter overlay (base, hiver or both)
    python build.py --step osm               # only build the tiles (OSM / elevation samples)
    python build.py --step mkgmap            # only compile (tiles already built)
    python build.py --force                  # rebuild tiles even if already built
    python build.py --jobs 4                 # number of tiles built in parallel

Each grid tile is built once into config.TILES_DIR and reused by every coverage.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import traceback
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pyogrio
import shapely
from pyproj import Transformer
from rasterio.features import shapes, sieve
from rasterio.merge import merge
from scipy.ndimage import distance_transform_edt, gaussian_filter, map_coordinates
from skimage.measure import find_contours

import config
import coverage
import countries
import france
import osmzone
import legend
from coverage import Tile
from osmwriter import OsmWriter

TLM = next((config.DOWNLOAD_DIR / "swisstlm3d_2026-02_2056_5728.gpkg").glob("*.gpkg"), None)
SKI = config.DOWNLOAD_DIR / "skitouren_2056.gpkg"
SNOWSHOE = config.DOWNLOAD_DIR / "schneeschuhrouten_2056.gpkg"
DEM_RES = 5.0     # m
DEM_MARGIN = 100  # m of terrain read around a tile, so contours and slopes match across tiles
TILE_FORMAT = 3   # bump to invalidate already built tiles when the tile content changes


# --- Digital elevation model -----------------------------------------------------

class Dem:
    """Terrain at DEM_RES over a bbox, smoothed; `ok` is False when there is no data.

    swissALTI3D comes first, so Switzerland has priority; the other models (see
    config.ALTI_DIRS) only fill the cells not covered yet.
    """

    def __init__(self, bbox):
        e0, n0, e1, n1 = bbox
        keys = [f"{e}-{n}" for e in range(int(e0 // 1000), int(-(-e1 // 1000)))
                for n in range(int(n0 // 1000), int(-(-n1 // 1000)))]
        files = [d / f"{k}.tif" for d in config.ALTI_DIRS for k in keys]
        files = [f for f in files if f.exists()]
        self.ok = bool(files)
        if not self.ok:
            return
        z, transform = merge(files, bounds=bbox, res=DEM_RES, nodata=-9999)
        z = z[0].astype("float32")
        self.valid = z > -1000
        self.ok = bool(self.valid.any())
        if not self.ok:
            return
        # Fill voids (outside Switzerland) with the nearest value before smoothing
        if not self.valid.all():
            idx = distance_transform_edt(~self.valid, return_distances=False, return_indices=True)
            z = z[tuple(idx)]
        self.raw = z   # unsmoothed, for spot heights
        self.z = gaussian_filter(z, sigma=1.0)
        self.transform = transform
        self.left, self.top = transform.c, transform.f

    def to_xy(self, rows, cols):
        return self.left + (cols + 0.5) * DEM_RES, self.top - (rows + 0.5) * DEM_RES

    def sample(self, x, y, raw=False):
        """Bilinear elevation at LV95 coordinates; NaN outside valid data."""
        x, y = np.asarray(x, float), np.asarray(y, float)
        if not self.ok:
            return np.full(x.shape, np.nan)
        rows = (self.top - y) / DEM_RES - 0.5
        cols = (x - self.left) / DEM_RES - 0.5
        inside = (rows >= 0) & (rows <= self.z.shape[0] - 1) & (cols >= 0) & (cols <= self.z.shape[1] - 1)
        out = map_coordinates(self.raw if raw else self.z, [rows, cols], order=1, mode="nearest")
        ok = inside & map_coordinates(self.valid.astype("uint8"), [rows, cols], order=0, mode="nearest").astype(bool)
        return np.where(ok, out, np.nan)


def write_contours(dem: Dem, osm: OsmWriter, clip, step=10):
    lo, hi = np.floor(dem.z[dem.valid].min() / step) * step, np.ceil(dem.z[dem.valid].max() / step) * step
    for ele in np.arange(lo, hi + step, step):
        key = "contour_major" if ele % 100 == 0 else "contour_medium" if ele % 50 == 0 else "contour_minor"
        for c in find_contours(dem.z, ele, mask=dem.valid):
            x, y = dem.to_xy(c[:, 0], c[:, 1])
            geom = shapely.simplify(shapely.LineString(np.column_stack([x, y])), 1.5)
            if geom.length >= 40:
                osm.add(clip(geom), {"k": key, "ele": int(ele)})


SLOPE_CLASSES = [(30, "slope_30"), (35, "slope_35"), (40, "slope_40"), (45, "slope_45")]


def write_slopes(dem: Dem, osm: OsmWriter, clip, min_area=400):
    gy, gx = np.gradient(dem.z, DEM_RES)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    cls = np.zeros(slope.shape, "uint8")
    for i, (deg, _) in enumerate(SLOPE_CLASSES, 1):
        cls[slope >= deg] = i
    cls[~dem.valid] = 0
    cls = sieve(cls, size=int(min_area / DEM_RES**2), connectivity=8)
    for geom, v in shapes(cls, mask=cls > 0, transform=dem.transform, connectivity=8):
        poly = shapely.simplify(shapely.geometry.shape(geom), DEM_RES * 0.6)
        if not poly.is_empty and poly.area >= min_area:
            osm.add(clip(shapely.make_valid(poly)), {"k": SLOPE_CLASSES[int(v) - 1][1]})


# --- Hill shading (hgt) -----------------------------------------------------------------

HGT_N = 3601   # 1 arc-second
_TO_WGS = Transformer.from_crs(2056, 4326, always_xy=True)
_TO_LV95 = Transformer.from_crs(4326, 2056, always_xy=True)


def lonlat_bounds(bbox, margin=0.0):
    e0, n0, e1, n1 = bbox
    lons, lats = _TO_WGS.transform([e0, e1, e0, e1], [n0, n0, n1, n1])
    return min(lons) - margin, min(lats) - margin, max(lons) + margin, max(lats) + margin


def hgt_cells(bbox, margin=0.0):
    lon0, lat0, lon1, lat1 = lonlat_bounds(bbox, margin)
    return [(lat, lon) for lat in range(int(np.floor(lat0)), int(np.floor(lat1)) + 1)
            for lon in range(int(np.floor(lon0)), int(np.floor(lon1)) + 1)]


def hgt_name(cell):
    lat, lon = cell
    return f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}"


def hgt_samples(dem: Dem, tile: Tile):
    """Elevations of the 1" grid points falling inside the tile, per hgt cell."""
    out = {}
    lon0, lat0, lon1, lat1 = lonlat_bounds(tile.bounds, 0.001)
    e0, n0, e1, n1 = tile.bounds
    for cell in hgt_cells(tile.bounds, 0.001):
        lat, lon = cell
        r0, r1 = max(0, int((lat + 1 - lat1) * 3600)), min(HGT_N, int((lat + 1 - lat0) * 3600) + 2)
        c0, c1 = max(0, int((lon0 - lon) * 3600)), min(HGT_N, int((lon1 - lon) * 3600) + 2)
        if r0 >= r1 or c0 >= c1:
            continue
        rr, cc = np.mgrid[r0:r1, c0:c1]
        x, y = _TO_LV95.transform(lon + cc / 3600.0, lat + 1 - rr / 3600.0)
        inside = (x >= e0) & (x < e1) & (y >= n0) & (y < n1)
        z = dem.sample(x[inside], y[inside])
        keep = ~np.isnan(z)
        if keep.any():
            name = hgt_name(cell)
            out[f"{name}_r"] = rr[inside][keep].astype("int16")
            out[f"{name}_c"] = cc[inside][keep].astype("int16")
            out[f"{name}_z"] = np.round(z[keep]).astype("int16")
    return out


def assemble_hgt(cov: coverage.Coverage, out_dir):
    """Zipped .hgt files for the coverage, from the tile samples; no data = void."""
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    samples = [np.load(p) for t in cov.tiles if (p := config.TILES_DIR / t.name / "hgt.npz").exists()]
    for cell in hgt_cells(cov.bounds, 0.1):   # margin: mkgmap reads a bit beyond the map bounds
        name = hgt_name(cell)
        grid = np.full((HGT_N, HGT_N), -32768, ">i2")
        for s in samples:
            if f"{name}_z" in s:
                grid[s[f"{name}_r"], s[f"{name}_c"]] = s[f"{name}_z"]
        with zipfile.ZipFile(out_dir / f"{name}.hgt.zip", "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{name}.hgt", grid.tobytes())


# --- Base map ---------------------------------------------------------------------------

LANDCOVER = {
    "Fels": "rock", "Fels locker": "rock",
    "Lockergestein": "scree", "Lockergestein locker": "scree", "Felsbloecke": "scree", "Felsbloecke locker": "scree",
    "Gletscher": "glacier", "Schneefeld Toteis": "glacier",
    "Wald": "forest", "Wald offen": "forest",
    "Gebueschwald": "scrub", "Gehoelzflaeche": "scrub",
    "Feuchtgebiet": "wetland",
    "Stehende Gewaesser": "lake", "Fliessgewaesser": "river_area",
}
ROADS = {
    "Autobahn": "road_major", "Autostrasse": "road_major", "Ausfahrt": "road_major", "Einfahrt": "road_major",
    "10m Strasse": "road_major", "8m Strasse": "road_major", "6m Strasse": "road_major",
    "4m Strasse": "road", "3m Strasse": "road", "Platz": "road",
    "2m Weg": "track", "2m Wegfragment": "track",
    "1m Weg": "path", "1m Wegfragment": "path", "Markierte Spur": "path",
}
HIKING = {"Wanderweg": "hike_t1", "Bergwanderweg": "hike_t2", "Alpinwanderweg": "hike_t3"}
PEAKS = {"Hauptgipfel": "peak_major", "Alpiner Gipfel": "peak_major",
         "Gipfel": "peak", "Haupthuegel": "peak", "Huegel": "peak", "Felskopf": "peak",
         "Pass": "pass", "Strassenpass": "pass"}
HUT_USES = ["Schutzhuette", "Gasthof abgelegen"]


class TileContext:
    """Reading and clipping helpers bound to one tile."""

    def __init__(self, tile: Tile):
        self.tile = tile
        self.bounds = tile.bounds

    def read(self, layer, columns, path=TLM):
        return pyogrio.read_dataframe(path, layer=layer, columns=columns, bbox=self.bounds)

    def clip(self, geom):
        return shapely.clip_by_rect(geom, *self.bounds)

    def owns(self, point):
        """Half-open test, so a point on a tile edge belongs to exactly one tile."""
        e0, n0, e1, n1 = self.bounds
        return e0 <= point.x < e1 and n0 <= point.y < n1


def write_base(ctx: TileContext, osm: OsmWriter):
    clip = ctx.clip
    osm.add(clip(coverage.switzerland()), {"k": "land"})
    df = ctx.read("tlm_bb_bodenbedeckung", ["objektart"])
    for g, art in zip(df.geometry, df.objektart):
        if art in LANDCOVER:
            osm.add(clip(g), {"k": LANDCOVER[art]})

    df = ctx.read("tlm_bauten_gebaeude_footprint", ["objektart", "name", "nutzung"])
    for g in df.geometry:
        osm.add(clip(g), {"k": "building"})
    huts = df[df.nutzung.isin(HUT_USES) & df.name.notna()]
    for g, name in zip(huts.geometry, huts.name):
        if ctx.owns(g.centroid):
            osm.add(g.centroid, {"k": "hut", "name": name})

    df = ctx.read("tlm_strassen_strasse", ["objektart", "wanderwege", "kunstbaute", "name"])
    for g, art, hike, kb, name in zip(df.geometry, df.objektart, df.wanderwege, df.kunstbaute, df.name):
        if kb == "Tunnel" or art not in ROADS:
            continue
        key = ROADS[art]
        # Paths and tracks take the colour of their hiking category
        if key in ("track", "path") and hike in HIKING:
            key = HIKING[hike]
        osm.add(clip(g), {"k": key, "name": name if key.startswith("road") else None})

    df = ctx.read("tlm_gewaesser_fliessgewaesser", ["objektart", "verlauf", "name"])
    for g, art, verlauf, name in zip(df.geometry, df.objektart, df.verlauf, df.name):
        if art in ("Fliessgewaesser", "Bisse Suone") and verlauf in ("Oberirdisch", "Wasserfall", "Bruecke"):
            osm.add(clip(g), {"k": "stream", "name": name})

    df = ctx.read("tlm_oev_uebrige_bahn", ["name"])
    for g, name in zip(df.geometry, df.name):
        osm.add(clip(g), {"k": "aerialway", "name": name})
    df = ctx.read("tlm_oev_eisenbahn", ["kunstbaute", "name"])
    for g, kb in zip(df.geometry, df.kunstbaute):
        if kb != "Tunnel":
            osm.add(clip(g), {"k": "rail"})
    for g in ctx.read("tlm_bauten_leitung", ["objektart"]).geometry:
        osm.add(clip(g), {"k": "powerline"})

    # Names
    df = ctx.read("tlm_namen_name_pkt", ["objektart", "name", "hoehe"])
    for g, art, name, h in zip(df.geometry, df.objektart, df.name, df.hoehe):
        if art in PEAKS and name and ctx.owns(g):
            label = f"{name} {h:.0f}" if h == h and h > 0 else name
            osm.add(g, {"k": PEAKS[art], "name": label})
    df = ctx.read("tlm_name_gelaendename", ["name"])
    for g, name in zip(df.geometry, df.name):
        p = g.point_on_surface()
        if ctx.owns(p):
            osm.add(p, {"k": "locality", "name": name})
    df = ctx.read("tlm_namen_flurname", ["name"])
    for g, name in zip(df.geometry, df.name):
        if ctx.owns(g):
            osm.add(g, {"k": "locality", "name": name})
    df = ctx.read("tlm_namen_siedlungsname_zentrum", ["objektart", "name", "einwohnerkategorie"])
    for g, name, cat in zip(df.geometry, df.name, df.einwohnerkategorie):
        if ctx.owns(g):
            small = cat in ("< 20", "20 bis 49", "50 bis 99")
            osm.add(g, {"k": "hamlet" if small else "settlement", "name": name})


# --- Winter overlay --------------------------------------------------------------------

def oriented(geom, dem: Dem, upward: bool):
    """Orient each line uphill (or downhill) using the DEM, for direction arrows."""
    parts = []
    for line in shapely.get_parts(geom):
        if line.geom_type != "LineString":
            continue
        (x0, y0), (x1, y1) = line.coords[0][:2], line.coords[-1][:2]
        z0, z1 = dem.sample([x0, x1], [y0, y1])
        if not np.isnan(z0 + z1) and (z1 > z0) != upward:
            line = shapely.reverse(line)
        parts.append(line)
    return shapely.MultiLineString(parts) if parts else None


def route_label(*parts):
    return " ".join(p for p in parts if isinstance(p, str) and p)


def write_ski(ctx: TileContext, osm: OsmWriter, dem: Dem):
    clip = ctx.clip
    # access: 0 standard, 1 on foot only, 2 increased caution
    # direction: 0 both, 1 up, 2 down, 10/20 up/down at the start
    df = ctx.read("ski_network_2056", ["access", "direction"], path=next(SKI.glob("ski_network*.gpkg")))
    for g, access, direction in zip(df.geometry, df.access, df.direction):
        g = clip(shapely.force_2d(g))
        if access == 1:
            key = "ski_foot"
        elif access == 2:
            key = "ski_caution"
        elif direction in (1, 10):
            key, g = "ski_up", oriented(g, dem, upward=True)
        elif direction in (2, 20):
            key, g = "ski_down", oriented(g, dem, upward=False)
        else:
            key = "ski"
        osm.add(g, {"k": key})

    diff_col = f"difficulty_{config.LANG}"
    df = ctx.read("ski_routes_2056", ["route_nr", "target_name", diff_col], path=next(SKI.glob("ski_routes*.gpkg")))
    for g, nr, target, diff in zip(df.geometry, df.route_nr, df.target_name, df[diff_col]):
        if isinstance(nr, str):
            osm.add(clip(g), {"k": "ski_route_label", "name": route_label(nr, target, diff)})

    df = ctx.read("snowshoe_network_2056", ["access"], path=next(SNOWSHOE.glob("snowshoe_network*.gpkg")))
    for g in df.geometry:
        osm.add(clip(g), {"k": "snowshoe"})
    df = ctx.read("snowshoe_routes_2056", ["route_nr", "target_name", diff_col],
                  path=next(SNOWSHOE.glob("snowshoe_routes*.gpkg")))
    for g, nr, target, diff in zip(df.geometry, df.route_nr, df.target_name, df[diff_col]):
        if isinstance(nr, str):
            osm.add(clip(g), {"k": "snowshoe_route_label", "name": route_label(nr, target, diff)})


# geo.admin layer -> attribute holding the zone name
WILDLIFE_LAYERS = {"ch.bafu.wrz-wildruhezonen_portal": "wrz_name", "ch.bafu.wrz-jagdbanngebiete_select": "jb_name"}


def fetch_wildlife(bbox):
    """Wildlife quiet zones and protection areas from the geo.admin API (paged)."""
    feats = []
    for layer in WILDLIFE_LAYERS:
        offset = 0
        while True:
            q = urllib.parse.urlencode({
                "geometryType": "esriGeometryEnvelope", "geometry": ",".join(map(str, bbox)),
                "layers": f"all:{layer}", "tolerance": 0, "sr": 2056, "geometryFormat": "geojson",
                "limit": 50, "offset": offset})
            res = json.load(urllib.request.urlopen(f"{config.GEOADMIN_API}/identify?{q}"))["results"]
            feats += [(layer, r) for r in res]
            if len(res) < 50:
                break
            offset += 50
    return feats


def write_wildlife(ctx: TileContext, osm: OsmWriter):
    # The API provides de/fr/it attributes only
    lang = config.LANG if config.LANG in ("de", "fr", "it") else "de"
    for layer, f in fetch_wildlife(ctx.bounds):
        p = f["properties"]
        geom = ctx.clip(shapely.geometry.shape(f["geometry"]))
        if "wegtyp_de" in p:
            # Lines are the routes allowed inside a zone (paths, ski lifts)
            osm.add(geom, {"k": "wildlife_route", "name": p.get(f"wegtyp_{lang}")})
            continue
        binding = p.get("schutzs_de") == "rechtsverbindlich"
        name = (p.get(WILDLIFE_LAYERS[layer]) or "").split(" (Nr.")[0]
        period = (p.get("schutzzeit") or "").replace(" ", "")
        label = f"{name} {period}" if period and period != "01.01.-31.12." else name
        osm.add(geom, {"k": "wildlife_binding" if binding else "wildlife_advised", "name": label})
        osm.add(shapely.boundary(geom), {"k": "wildlife_edge_binding" if binding else "wildlife_edge_advised"})


# --- Tile build -------------------------------------------------------------------------

LAYERS = (("base", 0), ("hiver", 1))


def tile_osm(tile: Tile, layer_key: str):
    return config.TILES_DIR / tile.name / f"{tile.map_id(dict(LAYERS)[layer_key])}.osm.gz"


def french_depts(tile: Tile):
    """French departments with downloaded data that have land in the tile."""
    box = shapely.box(*tile.bounds)
    return [c for c in config.FRANCE_DEPTS if france.is_ready(c) and coverage.dept_outline(c).intersects(box)]




def build_tile(tile: Tile, force=False):
    """Build the OSM files and elevation samples of one tile; returns a status dict."""
    out = config.TILES_DIR / tile.name
    status_file = out / "status.json"
    depts, zones = french_depts(tile), countries.in_tile(tile.bounds)
    # Zones per country, e.g. {"it": ["AO", "TO~alps"]}: zones cut to the Alps are marked, so that
    # tiles built before the cut are rebuilt
    osm_zones = {c: [z.code + ("~alps" if z.code in config.ALPS_CLIPPED.get(c, []) else "")
                     for z in zones if z.country == c] for c in config.OSM_ZONES}
    # Departments, marked when cut to the Alps or still without OpenStreetMap rock
    fr_key = [c + ("~alps" if c in config.ALPS_CLIPPED["fr"] else "") + ("" if france.has_rock(c) else "~norock")
              for c in depts]
    # Format of the zones' OpenStreetMap data: a zone extracted again rebuilds its tiles
    osm_formats = sorted({osmzone.osm_format(z) for z in zones})
    if not force and status_file.exists():
        status = json.loads(status_file.read_text())
        if ((status.get("format"), status.get("lang"), status.get("fr", []), status.get("osm", []))
                == (TILE_FORMAT, config.LANG, fr_key, osm_formats)
                and all(status.get(c, []) == codes for c, codes in osm_zones.items())):
            return status | {"cached": True}
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)

    ctx = TileContext(tile)
    in_ch = coverage.switzerland().intersects(shapely.box(*tile.bounds))
    french = [ft for ft in (france.FrenchTile(ctx, c) for c in depts) if not ft.empty]
    others = []
    if zones:
        # Switzerland and the French departments keep priority over the OpenStreetMap zones
        box = shapely.box(*tile.bounds).buffer(500)
        foreign = shapely.union_all([shapely.intersection(shapely.make_valid(g), box) for g in
                                     [coverage.switzerland()] + [coverage.dept_outline(c) for c in depts]])
        outlines = {z.key: shapely.intersection(shapely.make_valid(z.outline()), box) for z in zones}
        others = osmzone.zone_tiles(ctx, zones, foreign, outlines)
    e0, n0, e1, n1 = tile.bounds
    dem = Dem((e0 - DEM_MARGIN, n0 - DEM_MARGIN, e1 + DEM_MARGIN, n1 + DEM_MARGIN))
    counts = {}
    with OsmWriter(tile_osm(tile, "base")) as osm:
        if dem.ok:
            write_contours(dem, osm, ctx.clip)
        if in_ch:
            write_base(ctx, osm)
        for ft in french:
            france.write_base(ft, osm, dem)
        for zt in others:
            osmzone.write_base(zt, osm, dem)
        counts["base"] = osm.count
    with OsmWriter(tile_osm(tile, "hiver")) as osm:
        if dem.ok:
            write_slopes(dem, osm, ctx.clip)
        if in_ch:
            write_ski(ctx, osm, dem)
            write_wildlife(ctx, osm)
        for ft in french:
            france.write_winter(ft, osm)
        for zt in others:
            osmzone.write_winter(zt, osm)
        counts["hiver"] = osm.count
    if dem.ok:
        np.savez_compressed(out / "hgt.npz", **hgt_samples(dem, tile))
    status = {"tile": tile.name, "format": TILE_FORMAT, "lang": config.LANG, "fr": fr_key, **osm_zones, "osm": osm_formats,
              "counts": counts}
    status_file.write_text(json.dumps(status))
    return status


def build_tiles(cov: coverage.Coverage, jobs: int, force: bool):
    in_ch = coverage.switzerland().intersects(shapely.union_all([shapely.box(*t.bounds) for t in cov.tiles]))
    if in_ch and TLM is None:
        raise SystemExit("swissTLM3D not found: run download.py first")
    # Fetch and cache the outlines once, before the workers start
    coverage.switzerland()
    coverage.alps()
    for code in config.FRANCE_DEPTS:
        coverage.dept_outline(code)
    for zone in countries.configured():
        zone.outline()
    done, failed = 0, []
    with ProcessPoolExecutor(jobs) as pool:
        futures = {pool.submit(build_tile, t, force): t for t in cov.tiles}
        for fut in as_completed(futures):
            done += 1
            try:
                s = fut.result()
            except Exception:
                # Report the tile and go on with the others: they are cached for the next run
                failed.append(futures[fut].name)
                print(f"  [{done}/{len(cov.tiles)}] {futures[fut].name}: FAILED", flush=True)
                traceback.print_exc()
                continue
            note = " (cached)" if s.get("cached") else ""
            print(f"  [{done}/{len(cov.tiles)}] {s['tile']}: base {s['counts']['base']}, "
                  f"hiver {s['counts']['hiver']} objects{note}", flush=True)
    if failed:
        raise SystemExit(f"{len(failed)} tile(s) failed: {', '.join(failed)}")


# --- mkgmap compilation -----------------------------------------------------------------

MKGMAP = next(config.TOOLS_DIR.glob("mkgmap-latest/mkgmap-*/mkgmap.jar"), None)
LEVELS = "0:24, 1:23, 2:21, 3:19, 4:17"
DEM_DISTS = "3312,6624,13248,26512,53024"   # one per level
# Above Garmin's own maps (mkgmap default 25), winter overlay on top
DRAW_PRIORITY = {"base": 40, "hiver": 41}
# Started by the window, without a console (Windows): no console window for Java, its output
# goes to the window's log with ours
NO_CONSOLE = ({"creationflags": subprocess.CREATE_NO_WINDOW, "stdout": sys.stdout, "stderr": subprocess.STDOUT}
              if os.name == "nt" and not (sys.stdout and sys.stdout.isatty()) else {})


def mkgmap(cov: coverage.Coverage, layer_key: str, jobs: int, dem_dir=None):
    work = config.WORK_DIR / "coverages" / cov.name
    out = work / f"img_{layer_key}"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    style = work / f"style_{layer_key}"
    legend.write_style(layer_key, style, LEVELS)
    family_id = cov.family_id + dict(LAYERS)[layer_key]
    typ = work / f"{layer_key}.typ.txt"
    legend.write_typ(layer_key, typ, family_id, config.LANG)

    title = f"{config.FAMILY_NAME} {layer_key} {cov.name}"
    # Options go to a config file (mkgmap -c): with hundreds of tiles, the command
    # line would exceed the Windows length limit.
    opts = [f"output-dir={out}", f"style-file={style}", "code-page=1252", f"max-jobs={jobs}",
            f"family-id={family_id}", "product-id=1", f"family-name={title}", f"series-name={title}",
            f"area-name={cov.name}", f"draw-priority={DRAW_PRIORITY[layer_key]}",
            "copyright-message=(c) swisstopo, OFEV/BAFU, CAS/SAC, IGN, INGV, BEV/geoland, LDBV, IGN-ES, "
            "Copernicus, OpenStreetMap, Camptocamp",
            "merge-lines",
            # Both maps are transparent: the base map is made opaque by its "land"
            # polygon over Switzerland only, so other maps still show abroad.
            "transparent"]
    if dem_dir:
        opts += [f"dem={dem_dir}", f"dem-dists={DEM_DISTS}", "show-profiles=1"]
    inputs = 0
    for t in cov.tiles:
        status_file = config.TILES_DIR / t.name / "status.json"
        if not status_file.exists():
            raise SystemExit(f"tile {t.name} not built: run build.py --step osm first")
        status = json.loads(status_file.read_text())
        if status["counts"][layer_key]:   # skip empty tiles
            # Garmin descriptions are limited to 50 characters
            opts += [f"mapname={t.map_id(dict(LAYERS)[layer_key])}", f"description={f'{title} {t.name}'[-50:]}",
                     f"input-file={tile_osm(t, layer_key)}"]
            inputs += 1
    if not inputs:
        print(f"  no {layer_key} data in this coverage, skipped")
        return
    opts += [f"description={title[:50]}", "gmapsupp", f"input-file={typ}"]
    args_file = work / f"{layer_key}.mkgmap.args"
    args_file.write_text("\n".join(opts) + "\n", encoding="utf-8")
    subprocess.run([config.JAVA, f"-Xmx{config.JAVA_MAX_HEAP}", "-jar", str(MKGMAP), "-c", str(args_file)],
                   check=True, **NO_CONSOLE)
    dest = config.OUTPUT_DIR / f"swisstopo_{cov.name}_{layer_key}.img"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(out / "gmapsupp.img", dest)
    print(f"  -> {dest} ({dest.stat().st_size / 1e6:.1f} MB)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage", default=config.COVERAGE,
                    help="area, switzerland, canton:XX[,YY], dept:NN, it/at/de/es[:XX], ad, bbox:E0,N0,E1,N1 "
                         "or alias (alpes, pyrenees)")
    ap.add_argument("--no-dem", action="store_true", help="without hill shading")
    ap.add_argument("--maps", nargs="+", choices=["base", "hiver"], default=["base", "hiver"],
                    help="maps to compile: base map, winter overlay or both")
    ap.add_argument("--step", choices=["all", "osm", "mkgmap"], default="all")
    ap.add_argument("--force", action="store_true", help="rebuild tiles even if already built")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()

    cov = coverage.resolve(args.coverage)
    print(f"Coverage {cov.name}: {len(cov.tiles)} tiles of {config.TILE_SIZE // 1000} km, family id {cov.family_id}")
    if args.step in ("all", "osm"):
        print("Tiles...")
        build_tiles(cov, args.jobs, args.force)
    if args.step in ("all", "mkgmap"):
        if "base" in args.maps:
            dem_dir = None
            if not args.no_dem:
                print("Hill shading (hgt)...")
                dem_dir = config.WORK_DIR / "coverages" / cov.name / "hgt"
                assemble_hgt(cov, dem_dir)
            print("mkgmap base...")
            mkgmap(cov, "base", args.jobs, dem_dir)
        if "hiver" in args.maps:
            print("mkgmap winter...")
            mkgmap(cov, "hiver", args.jobs)


if __name__ == "__main__":
    main()
