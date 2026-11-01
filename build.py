"""Build the Garmin maps (.img) for the configured area.

    python build.py                 # everything
    python build.py --no-dem        # without hill shading
    python build.py --step osm      # only generate the OSM / hgt intermediates
    python build.py --step mkgmap   # only compile (intermediates already built)
"""
import argparse
import json
import shutil
import subprocess
import urllib.parse
import urllib.request

import numpy as np
import pyogrio
import shapely
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.features import shapes, sieve
from rasterio.merge import merge
from scipy.ndimage import distance_transform_edt, gaussian_filter, map_coordinates
from skimage.measure import find_contours

import config
import legend
from osmwriter import OsmWriter

TLM = next((config.DOWNLOAD_DIR / "swisstlm3d_2026-02_2056_5728.gpkg").glob("*.gpkg"), None)
SKI = config.DOWNLOAD_DIR / "skitouren_2056.gpkg"
SNOWSHOE = config.DOWNLOAD_DIR / "schneeschuhrouten_2056.gpkg"
DEM_RES = 5.0  # m


# --- Digital elevation model -----------------------------------------------------

class Dem:
    """swissALTI3D resampled to DEM_RES and smoothed, over the area bbox."""

    def __init__(self, bbox):
        tiles = sorted((config.DOWNLOAD_DIR / "alti3d").glob("*.tif"))
        z, transform = merge(tiles, bounds=bbox, res=DEM_RES, resampling=Resampling.average, nodata=-9999)
        z = z[0].astype("float32")
        self.valid = z > -1000
        # Fill voids (outside Switzerland) with the nearest value before smoothing
        if not self.valid.all():
            idx = distance_transform_edt(~self.valid, return_distances=False, return_indices=True)
            z = z[tuple(idx)]
        self.z = gaussian_filter(z, sigma=1.0)
        self.transform = transform
        self.left, self.top = transform.c, transform.f

    def to_xy(self, rows, cols):
        return self.left + (cols + 0.5) * DEM_RES, self.top - (rows + 0.5) * DEM_RES

    def sample(self, x, y):
        """Bilinear elevation at LV95 coordinates; NaN outside valid data."""
        rows = (self.top - np.asarray(y)) / DEM_RES - 0.5
        cols = (np.asarray(x) - self.left) / DEM_RES - 0.5
        inside = (rows >= 0) & (rows <= self.z.shape[0] - 1) & (cols >= 0) & (cols <= self.z.shape[1] - 1)
        out = map_coordinates(self.z, [rows, cols], order=1, mode="nearest")
        ok = inside & map_coordinates(self.valid.astype("uint8"), [rows, cols], order=0, mode="nearest").astype(bool)
        return np.where(ok, out, np.nan)


def write_contours(dem: Dem, osm: OsmWriter, step=10):
    lo, hi = np.floor(dem.z[dem.valid].min() / step) * step, np.ceil(dem.z[dem.valid].max() / step) * step
    n = 0
    for ele in np.arange(lo, hi + step, step):
        key = "contour_major" if ele % 100 == 0 else "contour_medium" if ele % 50 == 0 else "contour_minor"
        for c in find_contours(dem.z, ele, mask=dem.valid):
            x, y = dem.to_xy(c[:, 0], c[:, 1])
            geom = shapely.simplify(shapely.LineString(np.column_stack([x, y])), 1.5)
            if geom.length < 40:
                continue
            osm.add(geom, {"k": key, "ele": int(ele)})
            n += 1
    print(f"  {n} contour lines")


SLOPE_CLASSES = [(30, "slope_30"), (35, "slope_35"), (40, "slope_40"), (45, "slope_45")]


def write_slopes(dem: Dem, osm: OsmWriter, min_area=400):
    gy, gx = np.gradient(dem.z, DEM_RES)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    cls = np.zeros(slope.shape, "uint8")
    for i, (deg, _) in enumerate(SLOPE_CLASSES, 1):
        cls[slope >= deg] = i
    cls[~dem.valid] = 0
    cls = sieve(cls, size=int(min_area / DEM_RES**2), connectivity=8)
    n = 0
    for geom, v in shapes(cls, mask=cls > 0, transform=dem.transform, connectivity=8):
        poly = shapely.simplify(shapely.geometry.shape(geom), DEM_RES * 0.6)
        if poly.is_empty or poly.area < min_area:
            continue
        osm.add(shapely.make_valid(poly), {"k": SLOPE_CLASSES[int(v) - 1][1]})
        n += 1
    print(f"  {n} slope polygons")


def write_hgt(dem: Dem, out_dir):
    """1 arc-second (SRTM-like) .hgt tiles for mkgmap hill shading; no data = void (-32768)."""
    to_wgs = Transformer.from_crs(2056, 4326, always_xy=True)
    to_lv95 = Transformer.from_crs(4326, 2056, always_xy=True)
    b = config.BBOX
    lons, lats = to_wgs.transform([b[0], b[2], b[0], b[2]], [b[1], b[1], b[3], b[3]])
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 3601
    for lat0 in range(int(np.floor(min(lats))), int(np.floor(max(lats))) + 1):
        for lon0 in range(int(np.floor(min(lons))), int(np.floor(max(lons))) + 1):
            grid = np.full((n, n), -32768, ">i2")
            # Only the window covering the area is sampled
            r0, r1 = max(0, int((lat0 + 1 - max(lats)) * 3600) - 2), min(n, int((lat0 + 1 - min(lats)) * 3600) + 3)
            c0, c1 = max(0, int((min(lons) - lon0) * 3600) - 2), min(n, int((max(lons) - lon0) * 3600) + 3)
            rr, cc = np.mgrid[r0:r1, c0:c1]
            x, y = to_lv95.transform(lon0 + cc / 3600.0, lat0 + 1 - rr / 3600.0)
            z = dem.sample(x.ravel(), y.ravel()).reshape(rr.shape)
            grid[r0:r1, c0:c1] = np.where(np.isnan(z), -32768, np.round(z)).astype(">i2")
            name = f"N{lat0:02d}E{lon0:03d}.hgt"
            grid.tofile(out_dir / name)
            print(f"  {name}")


# --- Base map ---------------------------------------------------------------------------

def read(layer, columns, path=TLM):
    return pyogrio.read_dataframe(path, layer=layer, columns=columns, bbox=config.BBOX)


def clip(geom):
    return shapely.clip_by_rect(geom, *config.BBOX)


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


def write_base(osm: OsmWriter):
    df = read("tlm_bb_bodenbedeckung", ["objektart"])
    for g, art in zip(df.geometry, df.objektart):
        if art in LANDCOVER:
            osm.add(clip(g), {"k": LANDCOVER[art]})

    df = read("tlm_bauten_gebaeude_footprint", ["objektart", "name", "nutzung"])
    for g in df.geometry:
        osm.add(clip(g), {"k": "building"})
    huts = df[df.nutzung.isin(HUT_USES) & df.name.notna()]
    for g, name in zip(huts.geometry, huts.name):
        osm.add(g.centroid, {"k": "hut", "name": name})

    df = read("tlm_strassen_strasse", ["objektart", "wanderwege", "kunstbaute", "name"])
    for g, art, hike, kb, name in zip(df.geometry, df.objektart, df.wanderwege, df.kunstbaute, df.name):
        if kb == "Tunnel" or art not in ROADS:
            continue
        key = ROADS[art]
        # Paths and tracks take the colour of their hiking category
        if key in ("track", "path") and hike in HIKING:
            key = HIKING[hike]
        osm.add(clip(g), {"k": key, "name": name if key.startswith("road") else None})

    df = read("tlm_gewaesser_fliessgewaesser", ["objektart", "verlauf", "name"])
    for g, art, verlauf, name in zip(df.geometry, df.objektart, df.verlauf, df.name):
        if art in ("Fliessgewaesser", "Bisse Suone") and verlauf in ("Oberirdisch", "Wasserfall", "Bruecke"):
            osm.add(clip(g), {"k": "stream", "name": name})

    df = read("tlm_oev_uebrige_bahn", ["name"])
    for g, name in zip(df.geometry, df.name):
        osm.add(clip(g), {"k": "aerialway", "name": name})
    df = read("tlm_oev_eisenbahn", ["kunstbaute", "name"])
    for g, kb in zip(df.geometry, df.kunstbaute):
        if kb != "Tunnel":
            osm.add(clip(g), {"k": "rail"})
    for g in read("tlm_bauten_leitung", ["objektart"]).geometry:
        osm.add(clip(g), {"k": "powerline"})

    # Names
    df = read("tlm_namen_name_pkt", ["objektart", "name", "hoehe"])
    for g, art, name, h in zip(df.geometry, df.objektart, df.name, df.hoehe):
        if art in PEAKS and name:
            label = f"{name} {h:.0f}" if h == h and h > 0 else name
            osm.add(g, {"k": PEAKS[art], "name": label})
    df = read("tlm_name_gelaendename", ["name"])
    for g, name in zip(df.geometry, df.name):
        osm.add(clip(g).point_on_surface(), {"k": "locality", "name": name})
    df = read("tlm_namen_flurname", ["name"])
    for g, name in zip(df.geometry, df.name):
        osm.add(g, {"k": "locality", "name": name})
    df = read("tlm_namen_siedlungsname_zentrum", ["objektart", "name", "einwohnerkategorie"])
    for g, name, cat in zip(df.geometry, df.name, df.einwohnerkategorie):
        small = cat in ("< 20", "20 bis 49", "50 bis 99")
        osm.add(g, {"k": "hamlet" if small else "settlement", "name": name})


# --- Winter overlay --------------------------------------------------------------------

def oriented(geom, dem: Dem, upward: bool):
    """Orient each line uphill (or downhill) using the DEM, for direction arrows."""
    parts = []
    for line in shapely.get_parts(geom):
        (x0, y0), (x1, y1) = line.coords[0][:2], line.coords[-1][:2]
        z0, z1 = dem.sample([x0, x1], [y0, y1])
        if not np.isnan(z0 + z1) and (z1 > z0) != upward:
            line = shapely.reverse(line)
        parts.append(line)
    return shapely.MultiLineString(parts)


def route_label(*parts):
    return " ".join(p for p in parts if isinstance(p, str) and p)


def write_ski(osm: OsmWriter, dem: Dem):
    # access: 0 standard, 1 on foot only, 2 increased caution
    # direction: 0 both, 1 up, 2 down, 10/20 up/down at the start
    df = read("ski_network_2056", ["access", "direction"], path=next(SKI.glob("ski_network*.gpkg")))
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

    diff_col = f"difficulty_{config.DATA_LANG}"
    df = read("ski_routes_2056", ["route_nr", "target_name", diff_col], path=next(SKI.glob("ski_routes*.gpkg")))
    for g, nr, target, diff in zip(df.geometry, df.route_nr, df.target_name, df[diff_col]):
        if isinstance(nr, str):
            osm.add(clip(g), {"k": "ski_route_label", "name": route_label(nr, target, diff)})

    df = read("snowshoe_network_2056", ["access"], path=next(SNOWSHOE.glob("snowshoe_network*.gpkg")))
    for g in df.geometry:
        osm.add(clip(g), {"k": "snowshoe"})
    df = read("snowshoe_routes_2056", ["route_nr", "target_name", diff_col],
              path=next(SNOWSHOE.glob("snowshoe_routes*.gpkg")))
    for g, nr, target, diff in zip(df.geometry, df.route_nr, df.target_name, df[diff_col]):
        if isinstance(nr, str):
            osm.add(clip(g), {"k": "snowshoe_route_label", "name": route_label(nr, target, diff)})


# geo.admin layer -> attribute holding the zone name
WILDLIFE_LAYERS = {"ch.bafu.wrz-wildruhezonen_portal": "wrz_name", "ch.bafu.wrz-jagdbanngebiete_select": "jb_name"}


def fetch_wildlife():
    """Wildlife quiet zones and protection areas from the geo.admin API (paged)."""
    feats = []
    for layer in WILDLIFE_LAYERS:
        offset = 0
        while True:
            q = urllib.parse.urlencode({
                "geometryType": "esriGeometryEnvelope", "geometry": ",".join(map(str, config.BBOX)),
                "layers": f"all:{layer}", "tolerance": 0, "sr": 2056, "geometryFormat": "geojson",
                "limit": 50, "offset": offset})
            res = json.load(urllib.request.urlopen(f"https://api3.geo.admin.ch/rest/services/api/MapServer/identify?{q}"))["results"]
            feats += [(layer, r) for r in res]
            if len(res) < 50:
                break
            offset += 50
    return feats


def write_wildlife(osm: OsmWriter):
    # The API provides de/fr/it attributes only
    lang = config.DATA_LANG if config.DATA_LANG in ("de", "fr", "it") else "de"
    zones = routes = 0
    for layer, f in fetch_wildlife():
        p = f["properties"]
        geom = clip(shapely.geometry.shape(f["geometry"]))
        if "wegtyp_de" in p:
            # Lines are the routes allowed inside a zone (paths, ski lifts)
            osm.add(geom, {"k": "wildlife_route", "name": p.get(f"wegtyp_{lang}")})
            routes += 1
            continue
        binding = p.get("schutzs_de") == "rechtsverbindlich"
        name = (p.get(WILDLIFE_LAYERS[layer]) or "").split(" (Nr.")[0]
        period = (p.get("schutzzeit") or "").replace(" ", "")
        label = f"{name} {period}" if period and period != "01.01.-31.12." else name
        osm.add(geom, {"k": "wildlife_binding" if binding else "wildlife_advised", "name": label})
        osm.add(shapely.boundary(geom), {"k": "wildlife_edge_binding" if binding else "wildlife_edge_advised"})
        zones += 1
    print(f"  {zones} wildlife zones, {routes} allowed routes")


# --- mkgmap compilation -----------------------------------------------------------------

MKGMAP = next(config.TOOLS_DIR.glob("mkgmap-latest/mkgmap-*/mkgmap.jar"), None)
LEVELS = "0:24, 1:23, 2:21, 3:19, 4:17"
DEM_DISTS = "3312,6624,13248,26512,53024"   # one per level


def mkgmap(map_key, osm_file, family_id, priority, dem_dir=None, transparent=False):
    work = config.WORK_DIR / config.ZONE
    out = work / f"img_{map_key}"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    style = work / f"style_{map_key}"
    legend.write_style(map_key, style, LEVELS)
    typ = work / f"{map_key}.typ.txt"
    legend.write_typ(map_key, typ, family_id, config.LANG)
    title = f"{config.FAMILY_NAME} {map_key} {config.ZONE}"
    cmd = [config.JAVA, f"-Xmx{config.JAVA_MAX_HEAP}", "-jar", str(MKGMAP),
           f"--output-dir={out}", f"--style-file={style}", "--code-page=1252",
           f"--family-id={family_id}", "--product-id=1", f"--family-name={title}", f"--series-name={title}",
           f"--description={title}", f"--area-name={config.ZONE}", f"--draw-priority={priority}",
           "--copyright-message=(c) swisstopo, OFEV/BAFU, CAS/SAC", "--merge-lines", "--gmapsupp",
           f"--mapname={config.MAP_ID_BASE + (family_id - config.FAMILY_ID) * 1000 + 1}"]
    if transparent:
        cmd.append("--transparent")
    if dem_dir:
        cmd += [f"--dem={dem_dir}", f"--dem-dists={DEM_DISTS}", "--show-profiles=1"]
    cmd += [str(osm_file), str(typ)]
    subprocess.run(cmd, check=True)
    dest = config.OUTPUT_DIR / f"swisstopo_{config.ZONE}_{map_key}.img"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(out / "gmapsupp.img", dest)
    print(f"  -> {dest} ({dest.stat().st_size / 1e6:.1f} MB)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-dem", action="store_true", help="without hill shading")
    ap.add_argument("--step", choices=["all", "osm", "mkgmap"], default="all")
    args = ap.parse_args()

    work = config.WORK_DIR / config.ZONE
    base_osm, winter_osm, hgt_dir = work / "base.osm", work / "hiver.osm", work / "hgt"
    if args.step in ("all", "osm"):
        print("swissALTI3D DEM...")
        dem = Dem(config.BBOX)
        print("Base map...")
        with OsmWriter(base_osm) as osm:
            write_contours(dem, osm)
            write_base(osm)
        print("Winter overlay...")
        with OsmWriter(winter_osm) as osm:
            write_slopes(dem, osm)
            write_ski(osm, dem)
            write_wildlife(osm)
        if not args.no_dem:
            print("Hill shading (hgt)...")
            write_hgt(dem, hgt_dir)
    if args.step in ("all", "mkgmap"):
        print("mkgmap base...")
        mkgmap("base", base_osm, config.FAMILY_ID, 25, None if args.no_dem else hgt_dir)
        print("mkgmap winter...")
        mkgmap("hiver", winter_osm, config.FAMILY_ID + 1, 30, transparent=True)


if __name__ == "__main__":
    main()
