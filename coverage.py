"""Tile grid and coverages (which tiles make up a map).

The LV95 plane is cut into square tiles of config.TILE_SIZE. A tile is named
after its south-west corner in km (e.g. "2570-1080") and gets a fixed 8-digit
Garmin map id, so a tile built once can be reused by every coverage.
"""
import json
import math
import shutil
import urllib.parse
import urllib.request
import zipfile
import zlib
from dataclasses import dataclass

import numpy as np
import pyogrio
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
        row = (self.n - N_ORIGIN) // config.TILE_SIZE
        if not -N_ROWS // 2 <= row < N_ROWS // 2:
            raise ValueError(f"tile {self.name} is too far north or south of the grid origin")
        index = ((self.e - E_ORIGIN) // config.TILE_SIZE) * N_ROWS + row
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


def _istat(layer: str):
    """ISTAT boundary layer ("ProvCM" provinces, "Com" municipalities) in LV95, downloaded once."""
    d = config.ITALY_DIR / "istat"
    shp = next(d.glob(f"{layer}*/*.shp"), None) if d.exists() else None
    if shp is None:
        d.mkdir(parents=True, exist_ok=True)
        archive = d / "limiti.zip"
        req = urllib.request.Request(config.ISTAT_BOUNDARIES, headers={"User-Agent": config.USER_AGENT})
        with urllib.request.urlopen(req) as r, open(archive, "wb") as f:
            shutil.copyfileobj(r, f)
        with zipfile.ZipFile(archive) as z:
            z.extractall(d)
        archive.unlink()
        shp = next(d.glob(f"{layer}*/*.shp"))
    return pyogrio.read_dataframe(shp).to_crs(2056)


def italy_zone(code: str):
    """Outline of an Italian zone in LV95 (cached): a province (ISTAT abbreviation),
    or GP, the Piedmont side of the Gran Paradiso."""
    cache = config.ITALY_DIR / code / "outline.wkb"
    if cache.exists():
        return shapely.from_wkb(cache.read_bytes())
    if code == "GP":
        df = _istat("Com")
        df = df[df.COMUNE.isin(config.GRAN_PARADISO) & (df.COD_PROV == 1)]
    else:
        df = _istat("ProvCM")
        df = df[df.SIGLA == code]
    if df.empty:
        raise ValueError(f"unknown Italian zone {code!r}: use a province abbreviation (AO, VB...) or GP")
    geom = shapely.union_all(df.geometry.values)
    cache.parent.mkdir(parents=True, exist_ok=True)
    # ISTAT codes: the region picks the OpenStreetMap extract, the province the family id
    (cache.parent / "region").write_text(str(int(df.COD_REG.iloc[0])))
    (cache.parent / "province").write_text(str(int(df.COD_PROV.iloc[0])))
    cache.write_bytes(shapely.to_wkb(geom))
    return geom


def italy_zone_code(code: str, what: str) -> int:
    """ISTAT "region" or "province" code of an Italian zone."""
    italy_zone(code)
    return int((config.ITALY_DIR / code / what).read_text())


def _gisco(dataset: str, filename: str):
    """GISCO (Eurostat) boundary file, downloaded once, in LV95."""
    path = config.DOWNLOAD_DIR / "gisco" / filename
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(f"{config.GISCO}/{dataset}/geojson/{filename}",
                                     headers={"User-Agent": config.USER_AGENT})
        with urllib.request.urlopen(req, timeout=600) as r, open(path.with_suffix(".part"), "wb") as f:
            shutil.copyfileobj(r, f)
        path.with_suffix(".part").replace(path)
    return pyogrio.read_dataframe(path).to_crs(2056)


def nuts_zone(country: str, code: str):
    """Outline in LV95 (cached) of a NUTS 3 region (e.g. AT332), or of a whole country
    when the code is a country code (AD)."""
    cache = config.DOWNLOAD_DIR / country / code / "outline.wkb"
    if cache.exists():
        return shapely.from_wkb(cache.read_bytes())
    if len(code) == 2:
        df = _gisco("countries", "CNTR_RG_01M_2024_4326.geojson")
        df = df[df.CNTR_ID == code]
    else:
        df = _gisco("nuts", "NUTS_RG_01M_2024_4326_LEVL_3.geojson")
        df = df[df.NUTS_ID == code]
    if df.empty:
        raise ValueError(f"unknown zone {code!r}: use a NUTS 3 code (e.g. AT332) or a country code (AD)")
    geom = shapely.make_valid(shapely.union_all(df.geometry.values))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(shapely.to_wkb(geom))
    return geom


def _osm_country(country: str, arg: str) -> Coverage:
    """Coverage of zones of a country mapped from OpenStreetMap (all its configured zones
    when no code is given)."""
    import countries
    configured = config.OSM_ZONES[country]
    codes = [c.strip().upper() for c in arg.split(",")] if arg else configured
    geom = shapely.union_all([countries.Zone(country, c).outline() for c in codes])
    if country == "it":
        prov = 99 if codes[0] == "GP" else italy_zone_code(codes[0], "province") % 100
        fid = config.ITALY_FAMILY_ID + 2 * prov
    else:
        fid = config.OSM_FAMILY_ID + 2 * (zlib.crc32(",".join(codes).encode()) % 1000)
    if set(codes) == set(configured):
        name = country
    elif country == "it":
        name = "it" + "-".join(codes).lower()
    else:
        name = "-".join(codes).lower()
    return Coverage(name, fid, tiles_for(geom))


def resolve(spec: str) -> Coverage:
    """Coverage from a spec: area name, "switzerland", "canton:VS,VD", "dept:74,73",
    "it:AO,GP", "at:AT332", "de:DE27E", "es:ES241", "ad" (or "it", "at"... for all the
    configured zones of a country), "bbox:E0,N0,E1,N1", an alias of config.ALIASES, or
    several of them joined with "+"."""
    if spec in config.ALIASES:
        cov = resolve(config.ALIASES[spec])
        return Coverage(spec, cov.family_id, cov.tiles)
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
    if kind in config.OSM_ZONES:
        return _osm_country(kind, arg)
    if kind == "bbox":
        bbox = [float(v) for v in arg.split(",")]
        return Coverage("custom", config.CUSTOM_BBOX_FAMILY_ID, tiles_for(shapely.box(*bbox)))
    raise ValueError(f"unknown coverage {spec!r}: use an area ({', '.join(config.AREAS)}), "
                     "switzerland, canton:XX, dept:NN, it[:XX], at[:XX], de[:XX], es[:XX], ad, bbox:E0,N0,E1,N1 "
                     f"or an alias ({', '.join(config.ALIASES)}), joined with + if needed")
