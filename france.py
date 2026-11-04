"""French data (per department): download and conversion to the map categories.

Sources:
- IGN BD TOPO (vector) and RGE ALTI 5 m (terrain), licence Etalab 2.0;
- OpenStreetMap rock and scree areas (missing from BD TOPO), licence ODbL;
- Camptocamp ski touring routes, licence CC BY-SA 3.0.

Switzerland has priority: French data only fills the part of a tile that lies in
the department and outside Switzerland.
"""
import json
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import py7zr
import pyogrio
import rasterio
import shapely
from pyproj import Transformer
from rasterio.merge import merge
from rasterio.warp import Resampling, reproject

import config
import coverage

L93, LV95 = 2154, 2056
_LV95_TO_L93 = Transformer.from_crs(LV95, L93, always_xy=True)
_LV95_TO_WGS84 = Transformer.from_crs(LV95, 4326, always_xy=True)
_LV95_TO_3857 = Transformer.from_crs(LV95, 3857, always_xy=True)


def dept_dir(code) -> Path:
    return config.FRANCE_DIR / code


def is_ready(code) -> bool:
    return (dept_dir(code) / "ready").exists()


def bdtopo_path(code) -> Path:
    return next(dept_dir(code).glob("BDTOPO*/**/*.gpkg"))


# --- Download ------------------------------------------------------------------------

def _get(url, **kw):
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT}, **kw)
    return urllib.request.urlopen(req, timeout=600)


def ign_latest(resource, code, pattern):
    """Download URLs of the latest IGN product matching pattern for a department."""
    feed = _get(f"{config.IGN_DOWNLOAD}/resource/{resource}?zone=D{code.zfill(3)}&limit=200").read().decode()
    titles = [t for t in re.findall(r"<title>([^<]+)</title>", feed) if re.search(pattern, t)]
    if not titles:
        raise RuntimeError(f"no {resource} product matching {pattern!r} for department {code}")
    latest = max(titles, key=lambda t: t[-10:])   # titles end with the edition date
    entry = _get(f"{config.IGN_DOWNLOAD}/resource/{resource}/{latest}").read().decode()
    return sorted(set(re.findall(r'href="([^"]+\.7z(?:\.\d+)?)"', entry)))


def extract(archive, out_dir, suffixes):
    with py7zr.SevenZipFile(archive) as z:
        z.extract(path=out_dir, targets=[n for n in z.getnames() if n.lower().endswith(suffixes)])


def download_bdtopo(code, fetch):
    d = dept_dir(code)
    if any(d.glob("BDTOPO*/**/*.gpkg")):
        return
    urls = ign_latest("BDTOPO", code, r"^BDTOPO_.*_TOUSTHEMES_GPKG_LAMB93_D\d+_")
    print(f"  BD TOPO {code}: {urls[0].rsplit('/', 1)[-1]}")
    archive = fetch(urls[0], d / urls[0].rsplit("/", 1)[-1])
    extract(archive, d, (".gpkg",))
    archive.unlink()


def download_rgealti(code, fetch, outline):
    """RGE ALTI 5 m, reprojected to LV95 5 m files of 1 km2 (same layout as swissALTI3D)."""
    d = dept_dir(code)
    marker = d / "rgealti.done"
    if marker.exists():
        return
    urls = ign_latest("RGEALTI", code, r"^RGEALTI_.*_5M_ASC_LAMB93-IGN69_D\d+_")
    print(f"  RGE ALTI {code}: {urls[0].rsplit('/', 1)[-1]}")
    archive = fetch(urls[0], d / urls[0].rsplit("/", 1)[-1])
    tmp = d / "rgealti_tmp"
    extract(archive, tmp, (".asc",))

    # ASCII grids -> GeoTIFF (Lambert-93), with their bounds for a quick lookup
    sources = []
    for asc in sorted(tmp.rglob("*.asc")):
        with rasterio.open(asc) as r:
            z, transform, nodata = r.read(1), r.transform, r.nodata
        tif = asc.with_suffix(".tif")
        with rasterio.open(tif, "w", driver="GTiff", width=z.shape[1], height=z.shape[0], count=1,
                           dtype="float32", crs=f"EPSG:{L93}", transform=transform, nodata=nodata) as w:
            w.write(z.astype("float32"), 1)
        asc.unlink()
        sources.append((shapely.box(*rasterio.transform.array_bounds(*z.shape, transform)), tif))

    # One LV95 km2 file per target cell around the department
    config.ALTI_FR_DIR.mkdir(parents=True, exist_ok=True)
    area = outline.buffer(1000)
    e0, n0, e1, n1 = (int(v // 1000) for v in area.bounds)
    done = 0
    for e in range(e0, e1 + 1):
        for n in range(n0, n1 + 1):
            dest = config.ALTI_FR_DIR / f"{e}-{n}.tif"
            cell = shapely.box(e * 1000, n * 1000, e * 1000 + 1000, n * 1000 + 1000)
            if dest.exists() or not area.intersects(cell):
                continue
            xs, ys = _LV95_TO_L93.transform([e * 1000, e * 1000 + 1000] * 2, [n * 1000] * 2 + [n * 1000 + 1000] * 2)
            src_box = shapely.box(min(xs) - 20, min(ys) - 20, max(xs) + 20, max(ys) + 20)
            files = [f for b, f in sources if b.intersects(src_box)]
            if not files:
                continue
            z, transform = merge(files, bounds=src_box.bounds)
            out = np.full((200, 200), -9999, "float32")
            dst_transform = rasterio.transform.from_origin(e * 1000, n * 1000 + 1000, 5, 5)
            reproject(z[0], out, src_transform=transform, src_crs=f"EPSG:{L93}", src_nodata=-99999,
                      dst_transform=dst_transform, dst_crs=f"EPSG:{LV95}", dst_nodata=-9999,
                      resampling=Resampling.bilinear)
            if (out > -1000).any():
                with rasterio.open(dest, "w", driver="GTiff", width=200, height=200, count=1, dtype="float32",
                                   crs=f"EPSG:{LV95}", transform=dst_transform, nodata=-9999,
                                   compress="deflate", predictor=3) as w:
                    w.write(out, 1)
                done += 1
    print(f"  RGE ALTI {code}: {done} km2 converted")
    shutil.rmtree(tmp)
    archive.unlink()
    marker.touch()


def overpass(query, dest, attempts=4):
    """Run an Overpass query into a file, retrying when the server is busy."""
    for attempt in range(attempts):
        try:
            with _get(config.OVERPASS, data=urllib.parse.urlencode({"data": query}).encode()) as r, \
                    open(dest, "wb") as f:
                shutil.copyfileobj(r, f)
            return
        except urllib.error.HTTPError as e:
            if e.code not in (429, 502, 503, 504) or attempt == attempts - 1:
                raise
            time.sleep(30 * (attempt + 1))


def download_osm_rock(code, outline, chunks=4):
    """Rock and scree areas from OpenStreetMap (Overpass), saved in LV95.

    The department is queried in chunks x chunks pieces, small enough for the
    public Overpass server; areas found in several pieces are deduplicated.
    """
    dest = dept_dir(code) / "osm_rock.gpkg"
    if dest.exists():
        return
    e0, n0, e1, n1 = outline.bounds
    lons, lats = _LV95_TO_WGS84.transform([e0, e1, e0, e1], [n0, n0, n1, n1])
    lon_edges = np.linspace(min(lons), max(lons), chunks + 1)
    lat_edges = np.linspace(min(lats), max(lats), chunks + 1)
    print(f"  OpenStreetMap {code}: rock and scree ({chunks * chunks} queries)")
    frames = []
    for i in range(chunks):
        for j in range(chunks):
            bbox = f"{lat_edges[j]},{lon_edges[i]},{lat_edges[j + 1]},{lon_edges[i + 1]}"
            query = (f'[out:xml][timeout:300];(way["natural"~"^(bare_rock|scree|shingle)$"]({bbox});'
                     f'relation["natural"~"^(bare_rock|scree|shingle)$"]({bbox}););(._;>;);out body;')
            raw = dept_dir(code) / f"osm_rock_{i}_{j}.osm"
            overpass(query, raw)
            df = pyogrio.read_dataframe(raw, layer="multipolygons", columns=["osm_id", "osm_way_id", "natural"])
            frames.append(df[df["natural"].isin(["bare_rock", "scree", "shingle"])])
            raw.unlink()
    df = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=frames[0].crs)
    df = df.drop_duplicates(subset=["osm_id", "osm_way_id"]).to_crs(LV95)
    pyogrio.write_dataframe(df, dest, layer="rock")


def _c2c_label(doc, lang):
    loc = next((l for l in doc["locales"] if l["lang"] == lang), doc["locales"][0])
    name = " - ".join(p.strip() for p in (loc.get("title_prefix"), loc.get("title")) if p and p.strip())
    grades = ", ".join(g for g in (doc.get("labande_global_rating"), doc.get("ski_rating")) if g)
    return f"{name} ({grades})" if grades else name


def download_camptocamp(code, outline):
    """Ski touring routes from Camptocamp: tracks when available, otherwise a point."""
    dest = dept_dir(code) / "c2c_ski.gpkg"
    if dest.exists():
        return
    e0, n0, e1, n1 = outline.bounds
    xs, ys = _LV95_TO_3857.transform([e0, e1, e0, e1], [n0, n0, n1, n1])
    bbox = f"{min(xs):.0f},{min(ys):.0f},{max(xs):.0f},{max(ys):.0f}"
    docs, offset = [], 0
    while True:
        page = json.load(_get(f"{config.CAMPTOCAMP_API}/routes?bbox={bbox}&act=skitouring&limit=100&offset={offset}"))
        docs += page["documents"]
        offset += 100
        if offset >= page["total"]:
            break
    print(f"  Camptocamp {code}: {len(docs)} ski touring routes")
    # Tracks already fetched are kept in a cache, so an interrupted run resumes
    cache_file = dept_dir(code) / "c2c_tracks.json"
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    rows = []
    for doc in docs:
        geom, key = doc["geometry"], str(doc["document_id"])
        if geom.get("has_geom_detail"):
            if key not in cache:
                cache[key] = json.load(_get(f"{config.CAMPTOCAMP_API}/routes/{key}"))["geometry"]["geom_detail"]
                cache_file.write_text(json.dumps(cache))
                time.sleep(0.1)   # be gentle with the community API
            shape = _geojson_2d(cache[key])
        else:
            shape = _geojson_2d(geom["geom"])
        if shape is not None:
            rows.append({"id": doc["document_id"], "label": _c2c_label(doc, config.DATA_LANG), "geometry": shape})
    df = gpd.GeoDataFrame(rows, crs=3857).to_crs(LV95)
    pyogrio.write_dataframe(df, dest, layer="routes")


def _geojson_2d(text):
    """Shapely geometry from GeoJSON text, keeping x and y only (tracks may carry z and time)."""
    if not text:
        return None
    gj = json.loads(text)

    def xy(c):
        return [xy(p) for p in c] if isinstance(c[0], list) else c[:2]

    gj["coordinates"] = xy(gj["coordinates"])
    return shapely.geometry.shape(gj)


def download_dept(code, fetch):
    outline = coverage.department(code)
    download_bdtopo(code, fetch)
    download_rgealti(code, fetch, outline)
    download_osm_rock(code, outline)
    download_camptocamp(code, outline)
    (dept_dir(code) / "ready").touch()


# --- Tile content ------------------------------------------------------------------------

VEGETATION = {
    "Forêt fermée de feuillus": "forest", "Forêt fermée mixte": "forest", "Forêt fermée de conifères": "forest",
    "Forêt ouverte": "forest", "Bois": "forest", "Peupleraie": "forest", "Lande ligneuse": "scrub",
}
WATER = {
    "Glacier, névé": "glacier", "Lac": "lake", "Retenue": "lake", "Retenue-barrage": "lake", "Mare": "lake",
    "Réservoir-bassin": "lake", "Plan d'eau de gravière": "lake", "Ecoulement naturel": "river_area",
    "Canal": "river_area", "Marais": "wetland",
}
MAJOR_ROADS = {"Type autoroutier", "Route à 2 chaussées", "Bretelle"}
ROADS = {"Route à 1 chaussée", "Rond-point"}
TRACKS = {"Route empierrée", "Chemin"}
PATHS = {"Sentier", "Escalier"}
PEAKS = {"Sommet", "Pic", "Montagne"}
RELIEF_NAMES = {"Vallée", "Versant", "Crête", "Cirque", "Gorge", "Escarpement", "Plaine", "Dépression"}
RESERVES = {"Réserve naturelle", "Arrêté de protection", "Réserve biologique",
            "Réserve nationale de chasse et de faune sauvage"}
OSM_ROCK = {"bare_rock": "rock", "scree": "scree", "shingle": "scree"}


class FrenchTile:
    """Reads one department's data for one tile, limited to its French part."""

    def __init__(self, ctx, code):
        self.ctx, self.code = ctx, code
        box = shapely.box(*ctx.bounds)
        self.region = shapely.make_valid(shapely.difference(
            shapely.intersection(shapely.make_valid(coverage.department(code)), box),
            shapely.intersection(shapely.make_valid(coverage.switzerland()), box)))
        self.swiss_border = shapely.boundary(shapely.intersection(
            shapely.make_valid(coverage.switzerland()), box.buffer(500)))
        e0, n0, e1, n1 = ctx.bounds
        xs, ys = _LV95_TO_L93.transform([e0, e1, e0, e1], [n0, n0, n1, n1])
        self.bbox_l93 = (min(xs), min(ys), max(xs), max(ys))
        self.gpkg = bdtopo_path(code)

    @property
    def empty(self):
        return self.region.is_empty or self.region.area < 1

    def read(self, layer, columns, path=None, crs_bbox=None):
        path = path or self.gpkg
        bbox = self.ctx.bounds if crs_bbox == LV95 else self.bbox_l93
        df = pyogrio.read_dataframe(path, layer=layer, columns=columns, bbox=bbox)
        if df.crs is not None and df.crs.to_epsg() != LV95:
            df = df.to_crs(LV95)
        df["geometry"] = shapely.force_2d(df.geometry.values)
        return df

    def clip(self, geom):
        if not shapely.is_valid(geom):   # a few BD TOPO polygons self-intersect
            geom = shapely.make_valid(geom)
        return shapely.intersection(geom, self.region)

    def owns(self, point):
        """Point belongs to this tile's French part, away from the Swiss border.

        Summits and passes on the border are named by swisstopo; the 150 m margin
        avoids showing them twice with slightly different names or heights.
        """
        return (self.ctx.owns(point) and self.region.contains(point)
                and shapely.distance(point, self.swiss_border) > 150)


def _is_underground(position):
    try:
        return int(position) < 0
    except (TypeError, ValueError):
        return False


def write_base(ft: FrenchTile, osm, dem):
    clip = ft.clip
    osm.add(ft.region, {"k": "land"})

    df = ft.read("zone_de_vegetation", ["nature"])
    for g, nature in zip(df.geometry, df.nature):
        if nature in VEGETATION:
            osm.add(clip(g), {"k": VEGETATION[nature]})
    df = ft.read("surface_hydrographique", ["nature", "position_par_rapport_au_sol"])
    for g, nature, pos in zip(df.geometry, df.nature, df.position_par_rapport_au_sol):
        if nature in WATER and not _is_underground(pos):
            osm.add(clip(g), {"k": WATER[nature]})
    df = ft.read("rock", ["natural"], path=dept_dir(ft.code) / "osm_rock.gpkg", crs_bbox=LV95)
    for g, natural in zip(df.geometry, df.natural):
        osm.add(clip(g), {"k": OSM_ROCK[natural]})
    for g in ft.read("batiment", ["nature"]).geometry:
        osm.add(clip(g), {"k": "building"})

    df = ft.read("troncon_de_route", ["nature", "importance", "position_par_rapport_au_sol", "nom_collaboratif_gauche"])
    for g, nature, imp, pos, name in zip(df.geometry, df.nature, df.importance, df.position_par_rapport_au_sol,
                                         df.nom_collaboratif_gauche):
        if _is_underground(pos):
            continue
        if nature in MAJOR_ROADS or (nature in ROADS and imp in ("1", "2", "3")):
            key = "road_major"
        elif nature in ROADS:
            key = "road"
        elif nature in TRACKS:
            key = "track"
        elif nature in PATHS:
            key = "path"
        else:
            continue
        osm.add(clip(g), {"k": key, "name": name if key.startswith("road") else None})

    # Hiking routes: GR (red-white) and other marked routes (yellow)
    df = ft.read("itineraire_autre", ["nature", "toponyme", "numero"])
    for g, nature, name, number in zip(df.geometry, df.nature, df.toponyme, df.numero):
        if nature != "Itinéraire de randonnée pédestre":
            continue
        label = number or name
        key = "hike_gr" if str(label or "").upper().startswith("GR") else "hike_pr"
        osm.add(clip(g), {"k": key, "name": label})

    df = ft.read("troncon_hydrographique", ["nature", "position_par_rapport_au_sol"])
    for g, nature, pos in zip(df.geometry, df.nature, df.position_par_rapport_au_sol):
        if nature == "Ecoulement naturel" and not _is_underground(pos):
            osm.add(clip(g), {"k": "stream"})
    df = ft.read("troncon_de_voie_ferree", ["position_par_rapport_au_sol"])
    for g, pos in zip(df.geometry, df.position_par_rapport_au_sol):
        if not _is_underground(pos):
            osm.add(clip(g), {"k": "rail"})
    df = ft.read("transport_par_cable", ["nature", "toponyme"])
    for g, nature, name in zip(df.geometry, df.nature, df.toponyme):
        if not nature.startswith("Tapis roulant"):
            osm.add(clip(g), {"k": "aerialway", "name": name})
    for g in ft.read("ligne_electrique", []).geometry:
        osm.add(clip(g), {"k": "powerline"})

    # Names
    df = ft.read("detail_orographique", ["nature", "toponyme", "importance"])
    for g, nature, name, imp in zip(df.geometry, df.nature, df.toponyme, df.importance):
        if not name or not ft.owns(g):
            continue
        if nature in PEAKS or nature == "Col":
            ele = dem.sample([g.x], [g.y], raw=True)[0] if dem.ok else np.nan
            label = f"{name} {ele:.0f}" if not np.isnan(ele) else name
            key = "pass" if nature == "Col" else "peak_major" if imp in ("1", "2", "3", "4") else "peak"
            osm.add(g, {"k": key, "name": label})
        elif nature in RELIEF_NAMES:
            osm.add(g, {"k": "locality", "name": name})
    df = ft.read("lieu_dit_non_habite", ["toponyme"])
    for g, name in zip(df.geometry, df.toponyme):
        if name and ft.owns(g):
            osm.add(g, {"k": "locality", "name": name})
    df = ft.read("zone_d_habitation", ["nature", "toponyme", "importance"])
    for g, nature, name, imp in zip(df.geometry, df.nature, df.toponyme, df.importance):
        p = g.point_on_surface()
        if name and nature in ("Lieu-dit habité", "Quartier") and ft.owns(p):
            osm.add(p, {"k": "settlement" if imp in ("1", "2", "3", "4") else "hamlet", "name": name})
    df = ft.read("zone_d_activite_ou_d_interet", ["nature", "toponyme"])
    for g, nature, name in zip(df.geometry, df.nature, df.toponyme):
        p = g.point_on_surface()
        if nature == "Refuge" and name and ft.owns(p):
            osm.add(p, {"k": "hut", "name": name})


def write_winter(ft: FrenchTile, osm):
    clip = ft.clip
    df = ft.read("parc_ou_reserve", ["nature", "toponyme"])
    for g, nature, name in zip(df.geometry, df.nature, df.toponyme):
        if nature in RESERVES:
            g = clip(g)
            osm.add(g, {"k": "nature_reserve", "name": name})
            osm.add(shapely.boundary(g), {"k": "nature_reserve_edge"})

    df = ft.read("routes", ["label"], path=dept_dir(ft.code) / "c2c_ski.gpkg", crs_bbox=LV95)
    for g, label in zip(df.geometry, df.label):
        if "Point" in g.geom_type:
            if ft.owns(g):
                osm.add(g, {"k": "ski_c2c_point", "name": label})
        else:
            osm.add(clip(g), {"k": "ski_c2c", "name": label})
