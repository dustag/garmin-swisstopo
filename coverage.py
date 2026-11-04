"""Tile grid and coverages (which tiles make up a map).

The LV95 plane is cut into square tiles of config.TILE_SIZE. A tile is named
after its south-west corner in km (e.g. "2570-1080") and gets a fixed 8-digit
Garmin map id, so a tile built once can be reused by every coverage.
"""
import json
import math
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass

import numpy as np
import shapely
from pyproj import Transformer

import config

# Grid origin: south-west of Switzerland, so that tile indices stay small. Tiles
# west or south of it (France) get negative indices, which stay unique as long
# as the row index is within [-50, 50).
E_ORIGIN, N_ORIGIN = 2_480_000, 1_070_000
N_ROWS = 100
_WGS84_TO_LV95 = Transformer.from_crs(4326, 2056, always_xy=True)


@dataclass(frozen=True)
class Tile:
    e: int   # south-west corner, LV95 metres
    n: int

    @property
    def name(self):
        return f"{self.e // 1000}-{self.n // 1000}"

    @property
    def bounds(self):
        return (self.e, self.n, self.e + config.TILE_SIZE, self.n + config.TILE_SIZE)

    def map_id(self, layer: int):
        """8-digit Garmin map id; layer 0 = base, 1 = winter overlay."""
        index = ((self.e - E_ORIGIN) // config.TILE_SIZE) * N_ROWS + (self.n - N_ORIGIN) // config.TILE_SIZE
        return 65200000 + 2 * index + layer


@dataclass
class Coverage:
    name: str
    family_id: int
    tiles: list[Tile]

    @property
    def bounds(self):
        return (min(t.e for t in self.tiles), min(t.n for t in self.tiles),
                max(t.e for t in self.tiles) + config.TILE_SIZE, max(t.n for t in self.tiles) + config.TILE_SIZE)


def tiles_for(geom) -> list[Tile]:
    """Grid tiles intersecting a geometry (LV95)."""
    s = config.TILE_SIZE
    e0, n0, e1, n1 = geom.bounds
    tiles = []
    for e in range(math.floor((e0 - E_ORIGIN) / s) * s + E_ORIGIN, math.ceil(e1), s):
        for n in range(math.floor((n0 - N_ORIGIN) / s) * s + N_ORIGIN, math.ceil(n1), s):
            t = Tile(e, n)
            if geom.intersects(shapely.box(*t.bounds)):
                tiles.append(t)
    return tiles


def boundary(layer: str, field: str, value: str):
    """Boundary polygon from the geo.admin API (swissBOUNDARIES3D)."""
    q = urllib.parse.urlencode({"layer": layer, "searchText": value, "searchField": field, "contains": "false",
                                "returnGeometry": "true", "geometryFormat": "geojson", "sr": 2056})
    res = json.load(urllib.request.urlopen(f"{config.GEOADMIN_API}/find?{q}"))["results"]
    if not res:
        raise ValueError(f"{value!r} not found in {layer}")
    return shapely.union_all([shapely.geometry.shape(r["geometry"]) for r in res])


def switzerland():
    """Outline of Switzerland and Liechtenstein (cached in DOWNLOAD_DIR)."""
    cache = config.DOWNLOAD_DIR / "switzerland.wkb"
    if cache.exists():
        return shapely.from_wkb(cache.read_bytes())
    geom = shapely.union_all([boundary("ch.swisstopo.swissboundaries3d-land-flaeche.fill", "id", c)
                              for c in ("CH", "LI")])
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(shapely.to_wkb(geom))
    return geom


def department(code: str):
    """Outline of a French department in LV95, as the union of its communes (cached)."""
    cache = config.FRANCE_DIR / code / "outline.wkb"
    if cache.exists():
        return shapely.from_wkb(cache.read_bytes())
    url = f"{config.GEO_API_GOUV}/departements/{code}/communes?format=geojson&geometry=contour&fields=code"
    feats = json.load(urllib.request.urlopen(url))["features"]
    if not feats:
        raise ValueError(f"unknown French department {code!r}")
    geom = shapely.union_all([shapely.geometry.shape(f["geometry"]) for f in feats])
    geom = shapely.transform(geom, lambda xy: np.column_stack(_WGS84_TO_LV95.transform(xy[:, 0], xy[:, 1])))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(shapely.to_wkb(geom))
    return geom


def resolve(spec: str) -> Coverage:
    """Coverage from a spec: area name, "switzerland", "canton:VS,VD", "dept:74,73",
    "bbox:E0,N0,E1,N1", or several of them joined with "+"."""
    if "+" in spec:
        parts = [resolve(p) for p in spec.split("+")]
        tiles = sorted({t for c in parts for t in c.tiles}, key=lambda t: (t.e, t.n))
        fid = config.COMBINED_FAMILY_ID + 2 * (zlib.crc32(spec.encode()) % 1000)
        return Coverage("+".join(c.name for c in parts), fid, tiles)
    kind, _, arg = spec.partition(":")
    if spec in config.AREAS:
        fid, bbox = config.AREAS[spec]
        return Coverage(spec, fid, tiles_for(shapely.box(*bbox)))
    if spec == "switzerland":
        return Coverage("suisse", config.SWITZERLAND_FAMILY_ID, tiles_for(switzerland()))
    if kind == "canton":
        codes = [c.strip().upper() for c in arg.split(",")]
        unknown = set(codes) - set(config.CANTONS)
        if unknown:
            raise ValueError(f"unknown canton(s): {', '.join(sorted(unknown))}")
        geom = shapely.union_all([boundary("ch.swisstopo.swissboundaries3d-kanton-flaeche.fill", "ak", c)
                                  for c in codes])
        fid = config.CANTON_FAMILY_ID + 2 * config.CANTONS.index(codes[0])
        return Coverage("-".join(codes).lower(), fid, tiles_for(geom))
    if kind == "dept":
        codes = [c.strip().zfill(2) for c in arg.split(",")]
        geom = shapely.union_all([department(c) for c in codes])
        fid = config.DEPT_FAMILY_ID + 2 * int(codes[0])
        return Coverage("fr" + "-".join(codes), fid, tiles_for(geom))
    if kind == "bbox":
        bbox = [float(v) for v in arg.split(",")]
        return Coverage("custom", config.CUSTOM_BBOX_FAMILY_ID, tiles_for(shapely.box(*bbox)))
    raise ValueError(f"unknown coverage {spec!r}: use an area ({', '.join(config.AREAS)}), "
                     "switzerland, canton:XX, dept:NN or bbox:E0,N0,E1,N1, joined with + if needed")
