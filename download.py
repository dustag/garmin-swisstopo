"""Download the data of a coverage and the mkgmap tool (resumable).

    python download.py                         # coverage from .env
    python download.py --coverage canton:VS
    python download.py --coverage pyrenees

swissALTI3D tiles (2 m) are resampled to 5 m right after download and the
originals deleted: all of Switzerland takes ~40 GB at 2 m, a few GB at 5 m.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pyproj import Transformer

import shapely

import config
import countries
import coverage
import demsrc
import france
import osmzone

LEGACY_2M_DIR = config.DOWNLOAD_DIR / "alti3d"   # 2 m tiles kept by earlier versions


def fetch(url: str, dest: Path, quiet=False) -> Path:
    """Download url to dest, resuming a partial transfer if any."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Some servers (IGN) reject Python's default user agent
    headers = {"User-Agent": config.USER_AGENT}
    head = urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers=headers))
    total = int(head.headers.get("Content-Length", 0))
    if dest.exists() and dest.stat().st_size == total:
        return dest
    part = dest.with_name(dest.name + ".part")
    done = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers=headers | ({"Range": f"bytes={done}-"} if done else {}))
    show = total > 50e6 and not quiet
    with urllib.request.urlopen(req) as r, open(part, "ab" if done else "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if show:
                print(f"\r  {dest.name}: {done / 1e6:,.0f} / {total / 1e6:,.0f} MB", end="", flush=True)
    if show:
        print()
    part.replace(dest)
    return dest


def unzip(archive: Path) -> Path:
    out = archive.with_suffix("")
    if not out.exists():
        with zipfile.ZipFile(archive) as z:
            z.extractall(out)
    return out


def needed_km_tiles(cov: coverage.Coverage):
    """1 km swissALTI3D tiles covering the coverage tiles plus a 1 km margin."""
    keys = set()
    for t in cov.tiles:
        for e in range(t.e - 1000, t.e + config.TILE_SIZE + 1000, 1000):
            for n in range(t.n - 1000, t.n + config.TILE_SIZE + 1000, 1000):
                keys.add(f"{e // 1000}-{n // 1000}")
    return keys


def alti3d_urls(cov: coverage.Coverage, keys):
    """URLs of the latest swissALTI3D 2 m tile for each needed km tile."""
    to_wgs = Transformer.from_crs(2056, 4326, always_xy=True)
    e0, n0, e1, n1 = cov.bounds
    lon0, lat0 = to_wgs.transform(e0 - 1000, n0 - 1000)
    lon1, lat1 = to_wgs.transform(e1 + 1000, n1 + 1000)
    url = f"{config.STAC}/collections/ch.swisstopo.swissalti3d/items?bbox={lon0},{lat0},{lon1},{lat1}&limit=100"
    latest = {}
    while url:
        page = json.load(urllib.request.urlopen(url))
        for item in page["features"]:
            _, year, key = item["id"].split("_")
            if key not in keys:
                continue
            href = next(a["href"] for k, a in item["assets"].items() if k.endswith("_2_2056_5728.tif"))
            if key not in latest or year > latest[key][0]:
                latest[key] = (year, href)
        url = next((l["href"] for l in page["links"] if l["rel"] == "next"), None)
    return {key: href for key, (_, href) in latest.items()}


def get_alti(key, href):
    dest = config.ALTI_DIR / f"{key}.tif"
    if dest.exists():
        return
    legacy = next(LEGACY_2M_DIR.glob(f"swissalti3d_*_{key}_2_2056_5728.tif"), None) if LEGACY_2M_DIR.exists() else None
    for attempt in range(4):   # thousands of small files: retry transient network errors
        try:
            src = legacy or fetch(href, config.DOWNLOAD_DIR / "alti3d_tmp" / Path(href).name, quiet=True)
            break
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if attempt == 3:
                raise
            time.sleep(10 * (attempt + 1))
    demsrc.to_5m(src, dest)
    src.unlink()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage", default=config.COVERAGE,
                    help="area, switzerland, canton:XX[,YY], dept:NN, it/at/de/es[:XX], ad, bbox:E0,N0,E1,N1 "
                         "or alias (alpes, pyrenees)")
    ap.add_argument("--jobs", type=int, default=8, help="parallel downloads")
    args = ap.parse_args()

    cov = coverage.resolve(args.coverage)
    tiles = shapely.union_all([shapely.box(*t.bounds) for t in cov.tiles])
    print(f"Coverage {cov.name}: {len(cov.tiles)} tiles")
    # Swiss data, only when the coverage touches Switzerland
    if coverage.switzerland().intersects(tiles):
        keys = needed_km_tiles(cov)
        config.ALTI_DIR.mkdir(parents=True, exist_ok=True)
        todo = {k: h for k, h in alti3d_urls(cov, keys).items() if not (config.ALTI_DIR / f"{k}.tif").exists()}
        print(f"swissALTI3D: {len(todo)} km2 to fetch")
        with ThreadPoolExecutor(args.jobs) as pool:
            for i, _ in enumerate(pool.map(lambda kv: get_alti(*kv), todo.items()), 1):
                if i % 50 == 0 or i == len(todo):
                    print(f"\r  {i} / {len(todo)}", end="", flush=True)
        if todo:
            print()

        for key in ["skitouren", "schneeschuh", "tlm3d"]:
            url = config.SOURCES[key]
            archive = config.DOWNLOAD_DIR / Path(url).name
            if archive.with_suffix("").exists():   # already extracted (the archive may have been deleted)
                continue
            print(f"{key}: {url}")
            unzip(fetch(url, archive))

    # French departments touching the coverage
    for code in config.FRANCE_DEPTS:
        if not coverage.dept_outline(code).intersects(tiles):
            continue
        if not france.is_ready(code):
            print(f"France, department {code}:")
            france.download_dept(code, fetch)
        elif not france.has_rock(code):   # Overpass was down last time
            france.download_osm_rock(code, coverage.dept_outline(code))

    # Zones mapped from OpenStreetMap (Italy, Austria...) touching the coverage
    zones = [z for z in countries.configured() if z.area().intersects(tiles)
             and not (z.ready and osmzone.osm_ready(z))]
    if zones:
        print(f"OpenStreetMap zones {', '.join(z.code for z in zones)}:")
        osmzone.download_zones(zones, fetch)

    # Already there in the packaged application, whose folder is read-only
    if not next(config.TOOLS_DIR.glob("mkgmap-latest/mkgmap-*/mkgmap.jar"), None):
        unzip(fetch("https://www.mkgmap.org.uk/download/mkgmap-latest.zip", config.TOOLS_DIR / "mkgmap-latest.zip"))
    print("Downloads complete.")


if __name__ == "__main__":
    sys.exit(main())
