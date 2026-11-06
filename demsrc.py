"""Terrain models outside Switzerland, converted to the swissALTI3D layout: LV95 GeoTIFF
files of 1 km2 at 5 m, one directory per source (config.ALTI_DIRS sets their priority).

Each provider takes the area to cover (LV95) and the download function, and fills its
directory with the km2 cells of that area it has data for. Source files are deleted
once converted.
"""
import math
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import rasterio
import shapely
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject

import config

LV95 = 2056
RES = 5  # m


def from_lv95(geom, crs):
    t = Transformer.from_crs(LV95, crs, always_xy=True)
    return shapely.transform(geom, lambda xy: np.column_stack(t.transform(xy[:, 0], xy[:, 1])))


def km_cells(area, dest_dir: Path):
    """km2 cells (E, N in km) of the area that are not converted yet."""
    shapely.prepare(area)
    e0, n0, e1, n1 = (int(v // 1000) for v in area.bounds)
    return [(e, n) for e in range(e0, e1 + 1) for n in range(n0, n1 + 1)
            if not (dest_dir / f"{e}-{n}.tif").exists()
            and area.intersects(shapely.box(e * 1000, n * 1000, e * 1000 + 1000, n * 1000 + 1000))]


def to_5m(src: Path, dest: Path):
    """Average a fine terrain tile (swissALTI3D 2 m, Bavarian DGM1 1 m) down to 5 m, same CRS."""
    with rasterio.open(src) as r:
        size = int(round(r.width * r.res[0] / RES))
        z = r.read(1, out_shape=(size, size), resampling=Resampling.average, masked=True)
        profile = dict(driver="GTiff", width=size, height=size, count=1, dtype="float32", crs=r.crs,
                       transform=r.transform * r.transform.scale(r.width / size, r.height / size),
                       nodata=-9999, compress="deflate", predictor=3)
    tmp = dest.with_suffix(".tmp.tif")
    with rasterio.open(tmp, "w", **profile) as w:
        w.write(np.ma.filled(z.astype("float32"), -9999), 1)
    tmp.replace(dest)


BLOCK = 10  # km: cells are reprojected by blocks of BLOCK x BLOCK km2, much faster than one by one


def convert(paths, cells, dest_dir: Path, what: str):
    """Reproject source rasters (any CRS) into the LV95 5 m km2 cells; the first source
    with data wins where they overlap."""
    if not cells:
        return
    dest_dir.mkdir(parents=True, exist_ok=True)
    sources = [rasterio.open(p) for p in paths]
    to_src = {}
    for src in sources:
        to_src.setdefault(src.crs.to_string(), Transformer.from_crs(LV95, src.crs, always_xy=True))
    blocks = {}
    for e, n in cells:
        blocks.setdefault((e // BLOCK, n // BLOCK), []).append((e, n))
    print(f"  {what}: {len(cells)} km2 to convert")
    done = 0
    px = 1000 // RES   # pixels per km
    for (be, bn), block_cells in blocks.items():
        e0, n0 = be * BLOCK * 1000, bn * BLOCK * 1000
        size = BLOCK * px
        dst_transform = from_origin(e0, n0 + BLOCK * 1000, RES, RES)
        out = np.full((size, size), -9999, "float32")
        for src in sources:
            xs, ys = to_src[src.crs.to_string()].transform([e0, e0 + BLOCK * 1000] * 2,
                                                           [n0] * 2 + [n0 + BLOCK * 1000] * 2)
            if not shapely.box(min(xs), min(ys), max(xs), max(ys)).intersects(shapely.box(*src.bounds)):
                continue
            part = np.full((size, size), -9999, "float32")
            reproject(rasterio.band(src, 1), part, src_nodata=src.nodata, dst_transform=dst_transform,
                      dst_crs=f"EPSG:{LV95}", dst_nodata=-9999, resampling=Resampling.bilinear)
            out = np.where(out > -1000, out, part)
            if (out > -1000).all():
                break
        for e, n in block_cells:
            row, col = (bn * BLOCK + BLOCK - 1 - n) * px, (e - be * BLOCK) * px
            cell = out[row:row + px, col:col + px]
            if (cell > -1000).any():
                dest = dest_dir / f"{e}-{n}.tif"
                tmp = dest.with_suffix(".tmp.tif")
                with rasterio.open(tmp, "w", driver="GTiff", width=px, height=px, count=1, dtype="float32",
                                   crs=f"EPSG:{LV95}", transform=from_origin(e * 1000, n * 1000 + 1000, RES, RES),
                                   nodata=-9999, compress="deflate", predictor=3) as w:
                    w.write(cell, 1)
                tmp.replace(dest)
        done += len(block_cells)
        print(f"\r  {what}: {done} / {len(cells)} km2", end="", flush=True)
    print()
    for src in sources:
        src.close()


def _parallel(fn, items, jobs=8):
    with ThreadPoolExecutor(jobs) as pool:
        return [r for r in pool.map(fn, items) if r is not None]


def _get(url, dest: Path):
    """Download a small file (no resume); None when there is no data there (HTTP 404).

    Many small downloads: transient network errors are retried."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
            with urllib.request.urlopen(req, timeout=300) as r, open(dest.with_suffix(".part"), "wb") as f:
                shutil.copyfileobj(r, f)
            dest.with_suffix(".part").replace(dest)
            return dest
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt == 3:
                raise
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if attempt == 3:
                raise
        time.sleep(10 * (attempt + 1))


# --- Providers --------------------------------------------------------------------------

def austria(area, fetch):
    """DGM Österreich 10 m (geoland.at, CC BY 4.0): one GeoTIFF for the whole country."""
    cells = km_cells(area, config.ALTI_AT_DIR)
    if not cells:
        return
    d = config.DOWNLOAD_DIR / "at" / "dgm"
    tif = next(d.glob("*.tif"), None) if d.exists() else None
    if tif is None:
        archive = fetch(config.AUSTRIA_DGM, config.DOWNLOAD_DIR / "at" / "ogd-10m-at.zip")
        with zipfile.ZipFile(archive) as z:
            z.extractall(d)
        archive.unlink()
        tif = next(d.glob("*.tif"))
    convert([tif], cells, config.ALTI_AT_DIR, "DGM Österreich")
    shutil.rmtree(d)


def bavaria(area, fetch):
    """Bavarian DGM1 (CC BY 4.0): 1 km UTM 32 tiles at 1 m, averaged to 5 m on download."""
    cells = km_cells(area, config.ALTI_DE_DIR)
    if not cells:
        return
    tmp = config.DOWNLOAD_DIR / "de" / "dgm1_5m"
    tmp.mkdir(parents=True, exist_ok=True)
    x0, y0, x1, y1 = from_lv95(area, 25832).bounds
    keys = [f"{x}_{y}" for x in range(int(x0 // 1000), int(x1 // 1000) + 1)
            for y in range(int(y0 // 1000), int(y1 // 1000) + 1)]

    def get(key):
        dest = tmp / f"{key}.tif"
        if not dest.exists():
            src = _get(f"{config.BAVARIA_DGM1}/{key}.tif", tmp / f"{key}_1m.tif")
            if src is None:
                return None   # outside Bavaria
            to_5m(src, dest)
            src.unlink()
        return dest

    print(f"  DGM1 Bayern: up to {len(keys)} km2 to download (~4 MB each)")
    paths = _parallel(get, keys)
    # A virtual mosaic gathers the thousands of small tiles into one source
    convert([build_vrt(tmp / "dgm1.vrt", paths)], cells, config.ALTI_DE_DIR, "DGM1 Bayern")
    shutil.rmtree(tmp)


def spain(area, fetch):
    """MDT 5 m of the Spanish IGN (CC BY 4.0), read from its WCS by blocks of 0.1 degree."""
    cells = km_cells(area, config.ALTI_ES_DIR)
    if not cells:
        return
    tmp = config.DOWNLOAD_DIR / "es" / "mdt"
    tmp.mkdir(parents=True, exist_ok=True)
    wgs = from_lv95(area, 4326)
    lon0, lat0, lon1, lat1 = wgs.bounds
    blocks = [(lat / 10, lon / 10) for lat in range(math.floor(lat0 * 10), math.ceil(lat1 * 10))
              for lon in range(math.floor(lon0 * 10), math.ceil(lon1 * 10))
              if wgs.intersects(shapely.box(lon / 10, lat / 10, lon / 10 + 0.1, lat / 10 + 0.1))]

    def get(block):
        lat, lon = block
        dest = tmp / f"{lat:.1f}_{lon:.1f}.tif"
        if dest.exists():
            return dest
        q = urllib.parse.urlencode([("SERVICE", "WCS"), ("VERSION", "2.0.1"), ("REQUEST", "GetCoverage"),
                                    ("COVERAGEID", "Elevacion4258_5"), ("SUBSET", f"Lat({lat:.1f},{lat + 0.1:.1f})"),
                                    ("SUBSET", f"Long({lon:.1f},{lon + 0.1:.1f})"), ("FORMAT", "image/tiff")])
        raw = _get(f"{config.SPAIN_MDT_WCS}?{q}", tmp / f"{lat:.1f}_{lon:.1f}.raw.tif")
        if raw is None:
            return None
        # Integer metres without nodata: zero and below is outside Spain (or the sea)
        with rasterio.open(raw) as r:
            z = r.read(1).astype("float32")
            profile = r.profile | dict(dtype="float32", nodata=-9999, compress="deflate", predictor=3)
        z[z <= 0] = -9999
        with rasterio.open(dest, "w", **profile) as w:
            w.write(z, 1)
        raw.unlink()
        return dest

    print(f"  MDT España: {len(blocks)} blocks of 0.1° to download")
    paths = _parallel(get, blocks, jobs=4)
    convert([build_vrt(tmp / "mdt.vrt", paths)], cells, config.ALTI_ES_DIR, "MDT España")
    shutil.rmtree(tmp)


def copernicus(area, fetch):
    """Copernicus GLO-30 (30 m), where no national model is open (Andorra)."""
    cells = km_cells(area, config.ALTI_COP_DIR)
    if not cells:
        return
    tmp = config.DOWNLOAD_DIR / "copdem"
    lon0, lat0, lon1, lat1 = from_lv95(area, 4326).bounds
    paths = []
    for lat in range(math.floor(lat0), math.floor(lat1) + 1):
        for lon in range(math.floor(lon0), math.floor(lon1) + 1):
            name = (f"Copernicus_DSM_COG_10_{'N' if lat >= 0 else 'S'}{abs(lat):02d}_00_"
                    f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}_00_DEM")
            path = _get(f"{config.COPERNICUS_DEM}/{name}/{name}.tif", tmp / f"{name}.tif")
            if path:
                paths.append(path)
    convert(paths, cells, config.ALTI_COP_DIR, "Copernicus GLO-30")
    shutil.rmtree(tmp)


def build_vrt(vrt: Path, paths):
    """GDAL virtual mosaic of tiles sharing one CRS and resolution."""
    with rasterio.open(paths[0]) as r:
        crs, (rx, ry) = r.crs, r.res
    bounds = []
    for p in paths:
        with rasterio.open(p) as r:
            bounds.append((p, r.bounds, r.width, r.height))
    x0 = min(b.left for _, b, _, _ in bounds)
    y1 = max(b.top for _, b, _, _ in bounds)
    x1 = max(b.right for _, b, _, _ in bounds)
    y0 = min(b.bottom for _, b, _, _ in bounds)
    width, height = round((x1 - x0) / rx), round((y1 - y0) / ry)
    sources = "".join(
        f'<ComplexSource><SourceFilename relativeToVRT="0">{p}</SourceFilename><SourceBand>1</SourceBand>'
        f'<SrcRect xOff="0" yOff="0" xSize="{w}" ySize="{h}"/>'
        f'<DstRect xOff="{round((b.left - x0) / rx)}" yOff="{round((y1 - b.top) / ry)}" xSize="{w}" ySize="{h}"/>'
        f'<NODATA>-9999</NODATA></ComplexSource>'
        for p, b, w, h in bounds)
    vrt.write_text(
        f'<VRTDataset rasterXSize="{width}" rasterYSize="{height}"><SRS>{crs.to_wkt()}</SRS>'
        f'<GeoTransform>{x0}, {rx}, 0, {y1}, 0, {-ry}</GeoTransform>'
        f'<VRTRasterBand dataType="Float32" band="1"><NoDataValue>-9999</NoDataValue>{sources}</VRTRasterBand>'
        f'</VRTDataset>', encoding="utf-8")
    return vrt
