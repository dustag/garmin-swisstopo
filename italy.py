"""Italian terrain: TINITALY 1.1 (INGV), 10 m terrain model, licence CC BY 4.0.

The map data of Italy comes from OpenStreetMap (see osmzone.py), and the zone outlines
from ISTAT (see coverage.italy_zone).
"""
import shutil
import urllib.error
import zipfile

import shapely

import config
import demsrc

TINITALY_TILE = 50_000  # m, UTM 32


def tinitaly(area, fetch):
    """TINITALY 10 m, reprojected to LV95 5 m files of 1 km2 (same layout as swissALTI3D)."""
    cells = demsrc.km_cells(area, config.ALTI_IT_DIR)
    if not cells:
        return
    # 50 km source tiles, named after their south-west corner in UTM 32: w + N + E in 10 km
    src_dir = config.ITALY_DIR / "tinitaly"
    utm_area = demsrc.from_lv95(area, 32632)
    x0, y0, x1, y1 = utm_area.bounds
    paths = []
    for x in range(int(x0 // TINITALY_TILE) * TINITALY_TILE, int(x1), TINITALY_TILE):
        for y in range(int(y0 // TINITALY_TILE) * TINITALY_TILE, int(y1), TINITALY_TILE):
            if not utm_area.intersects(shapely.box(x, y, x + TINITALY_TILE, y + TINITALY_TILE)):
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
            paths.append(tif)
    demsrc.convert(paths, cells, config.ALTI_IT_DIR, "TINITALY")
    shutil.rmtree(src_dir, ignore_errors=True)
