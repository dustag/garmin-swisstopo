"""Download Swisstopo datasets and the mkgmap tool (resumable)."""
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

from pyproj import Transformer

import config


def fetch(url: str, dest: Path) -> Path:
    """Download url to dest, resuming a partial transfer if any."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    head = urllib.request.urlopen(urllib.request.Request(url, method="HEAD"))
    total = int(head.headers.get("Content-Length", 0))
    if dest.exists() and dest.stat().st_size == total:
        return dest
    part = dest.with_name(dest.name + ".part")
    done = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"Range": f"bytes={done}-"} if done else {})
    with urllib.request.urlopen(req) as r, open(part, "ab" if done else "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if total > 50e6:
                print(f"\r  {dest.name}: {done / 1e6:,.0f} / {total / 1e6:,.0f} MB", end="", flush=True)
    if total > 50e6:
        print()
    part.replace(dest)
    return dest


def unzip(archive: Path) -> Path:
    out = archive.with_suffix("")
    if not out.exists():
        with zipfile.ZipFile(archive) as z:
            z.extractall(out)
    return out


def alti3d_tiles(bbox):
    """URLs of the swissALTI3D 2 m tiles (latest year) covering an LV95 bbox."""
    to_wgs = Transformer.from_crs(2056, 4326, always_xy=True)
    lon0, lat0 = to_wgs.transform(bbox[0], bbox[1])
    lon1, lat1 = to_wgs.transform(bbox[2], bbox[3])
    url = f"{config.STAC}/collections/ch.swisstopo.swissalti3d/items?bbox={lon0},{lat0},{lon1},{lat1}&limit=100"
    latest = {}
    while url:
        page = json.load(urllib.request.urlopen(url))
        for item in page["features"]:
            _, year, tile = item["id"].split("_")
            e, n = (int(v) * 1000 for v in tile.split("-"))
            if not (bbox[0] <= e < bbox[2] and bbox[1] <= n < bbox[3]):
                continue
            href = next(a["href"] for k, a in item["assets"].items() if k.endswith("_2_2056_5728.tif"))
            if tile not in latest or year > latest[tile][0]:
                latest[tile] = (year, href)
        url = next((l["href"] for l in page["links"] if l["rel"] == "next"), None)
    return [href for _, href in latest.values()]


def main():
    d = config.DOWNLOAD_DIR
    tiles = alti3d_tiles(config.BBOX)
    print(f"swissALTI3D: {len(tiles)} tiles of 1 km2")
    for href in tiles:
        fetch(href, d / "alti3d" / Path(href).name)

    for key in ["skitouren", "schneeschuh", "tlm3d"]:
        url = config.SOURCES[key]
        archive = d / Path(url).name
        if archive.with_suffix("").exists():   # already extracted (the archive may have been deleted)
            continue
        print(f"{key}: {url}")
        unzip(fetch(url, archive))

    unzip(fetch("https://www.mkgmap.org.uk/download/mkgmap-latest.zip", config.TOOLS_DIR / "mkgmap-latest.zip"))
    print("Downloads complete.")


if __name__ == "__main__":
    sys.exit(main())
