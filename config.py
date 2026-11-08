"""Shared configuration for the Swisstopo -> Garmin (.img) pipeline.

Machine-specific paths and the default coverage are read from a `.env` file
(see `.env.example`).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

REPO_DIR = Path(__file__).resolve().parent
load_dotenv(REPO_DIR / ".env")

# Large data lives outside the repository
DATA_DIR = Path(os.environ.get("DATA_DIR", Path.home() / "swisstopo-data")).expanduser()
DOWNLOAD_DIR = DATA_DIR / "download"
ALTI_DIR = DOWNLOAD_DIR / "alti3d_5m"     # swissALTI3D resampled to 5 m, one file per km2
FRANCE_DIR = DOWNLOAD_DIR / "fr"          # French data, one sub-directory per department
ALTI_FR_DIR = DOWNLOAD_DIR / "rgealti_5m"  # RGE ALTI reprojected to LV95, 5 m, one file per km2
ITALY_DIR = DOWNLOAD_DIR / "it"           # Italian data, one sub-directory per zone
# Terrain outside Switzerland and France, reprojected to LV95, 5 m, one file per km2
ALTI_IT_DIR = DOWNLOAD_DIR / "tinitaly_5m"   # Italy, TINITALY 10 m
ALTI_AT_DIR = DOWNLOAD_DIR / "dgm_at_5m"     # Austria, DGM Österreich 10 m
ALTI_DE_DIR = DOWNLOAD_DIR / "dgm_by_5m"     # Bavaria, DGM1
ALTI_ES_DIR = DOWNLOAD_DIR / "mdt_es_5m"     # Spain, IGN MDT 5 m
ALTI_COP_DIR = DOWNLOAD_DIR / "copdem_5m"    # elsewhere (Andorra), Copernicus GLO-30
# Priority order of the terrain models: a cell takes the first one with data
ALTI_DIRS = [ALTI_DIR, ALTI_FR_DIR, ALTI_IT_DIR, ALTI_AT_DIR, ALTI_DE_DIR, ALTI_ES_DIR, ALTI_COP_DIR]
WORK_DIR = DATA_DIR / "work"
TILES_DIR = WORK_DIR / "tiles"             # per-tile intermediates, shared by all coverages
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", DATA_DIR / "output")).expanduser()
TOOLS_DIR = Path(os.environ.get("TOOLS_DIR", REPO_DIR / "tools")).expanduser()

# Java: JAVA_EXE, else the runtime bundled with the packaged application, else java from the PATH
_BUNDLED_JAVA = REPO_DIR / "jre" / "bin" / ("java.exe" if os.name == "nt" else "java")
JAVA = os.environ.get("JAVA_EXE") or (str(_BUNDLED_JAVA) if _BUNDLED_JAVA.exists() else "java")
JAVA_MAX_HEAP = os.environ.get("JAVA_MAX_HEAP", "4g")

# Coverage to build: an area name, "switzerland", "canton:VS[,VD...]", "dept:74[,73...]"
# (French departments), "it:AO[,GP...]", "at:AT332[,...]", "de:DE27E[,...]", "es:ES241[,...]"
# (zones of ITALY_ZONES, AUSTRIA_ZONES...), "it", "at", "de", "es", "ad" (all the zones of a
# country), "bbox:E0,N0,E1,N1" (LV95 metres) or an alias of ALIASES; several can be combined
# with "+", e.g. "canton:VS+dept:74". Can be overridden with --coverage.
COVERAGE = os.environ.get("COVERAGE", "telliers")

# Maps are cut into square tiles of a fixed LV95 grid. Each tile is built once
# and has a fixed Garmin map id, whatever the coverage it belongs to.
TILE_SIZE = 10_000  # m

# Named areas: name -> (Garmin family id, LV95 bbox (E min, N min, E max, N max)).
# Family ids must be unique among the maps installed on a device: base map uses
# the id, the winter overlay id + 1. Keep them even and below 6600.
AREAS = {
    # Les Monts Telliers from the Grand-St-Bernard tunnel car park
    "telliers": (6530, (2_574_000, 1_079_000, 2_584_000, 1_088_000)),
    # Village of Chavornay (VD) and its municipality, for testing on the plain
    "chavornay": (6532, (2_531_000, 1_170_000, 2_539_000, 1_177_000)),
}
SWITZERLAND_FAMILY_ID = 6520
CUSTOM_BBOX_FAMILY_ID = 6590
# Cantons in official order: family id = 6600 + 2 * index
CANTONS = ["ZH", "BE", "LU", "UR", "SZ", "OW", "NW", "GL", "ZG", "FR", "SO", "BS", "BL",
           "SH", "AR", "AI", "SG", "GR", "AG", "TG", "TI", "VD", "VS", "NE", "GE", "JU"]
CANTON_FAMILY_ID = 6600
# French departments: family id = 6700 + 2 * department number
DEPT_FAMILY_ID = 6700
# Italian zones: family id = 6800 + 2 * (ISTAT province code % 100); GP uses 99
ITALY_FAMILY_ID = 6800
# Austrian, German, Spanish and Andorran zones: family id = 9000 + 2 * (stable hash of the
# zone codes % 1000)
OSM_FAMILY_ID = 9000
# Combined coverages ("a+b"): family id = 7000 + 2 * (stable hash of the spec % 1000)
COMBINED_FAMILY_ID = 7000
FAMILY_NAME = "Swisstopo"

# Label language: fr, de, it or en. Place names always stay in their official local form.
LANG = os.environ.get("LANG_LABELS", "fr").lower()
if LANG not in ("fr", "de", "it", "en"):
    raise ValueError(f"LANG_LABELS must be fr, de, it or en (got {LANG!r})")

# Regions: the zones of each country that make them up (cantons, French departments,
# Italian provinces, NUTS 3 regions...). They are the aliases of the same name (see
# ALIASES), the buttons of the window, and the default zones of each country. The Alps
# take every zone with land in the perimeter of the Alpine Convention; the Alps are
# split along the Rhine - Splügen - Lake Como line, so that each map stays well below the
# 4 GB a Garmin file can hold.
REGIONS = {
    "alpes-ouest": {
        "ch": ["VS", "VD", "FR", "BE", "LU", "OW", "NW", "UR", "SZ", "GL", "TI"],
        "fr": ["74", "73", "38", "05", "04", "06", "26", "83", "84"],
        "it": ["AO", "VB", "VA", "CO", "TO", "CN", "BI", "VC", "NO", "IM", "SV"],
    },
    "alpes-est": {
        "ch": ["GR", "SG", "AR", "AI", "LI"],
        "it": ["SO", "BZ", "LC", "BG", "BS", "TN", "VR", "VI", "BL", "TV", "PN", "UD", "GO"],
        "at": ["AT341", "AT342", "AT331", "AT332", "AT333", "AT334", "AT335", "AT321", "AT322", "AT323",
               "AT211", "AT212", "AT213", "AT221", "AT222", "AT223", "AT224", "AT225", "AT226",
               "AT314", "AT315", "AT121", "AT122", "AT123", "AT126", "AT127", "AT111", "AT112", "AT113"],
        "de": ["DE27E", "DE27A", "DE273"],
    },
    "jura": {
        "ch": ["JU", "NE", "SO", "BL", "BS", "AG", "VD", "BE"],
        "fr": ["25", "39", "01"],
    },
    "pyrenees": {
        "fr": ["64", "65", "31", "09", "66"],
        "es": ["ES220", "ES241", "ES513", "ES512"],
        "ad": ["AD"],
    },
}
# Zones of the Alps partly outside the Alpine Convention (less than 90 % inside): they
# are cut to its perimeter, widened by ALPS_MARGIN, so that the plains (Turin, Verona,
# the Rhône valley, Graz...) do not weigh down the maps.
ALPS_CLIPPED = {
    "fr": ["26", "38", "83", "84"],
    "it": ["TO", "VC", "BI", "NO", "CN", "IM", "SV", "VA", "CO", "LC", "BG", "BS", "VR", "VI", "TV",
           "PN", "UD", "GO"],
    "at": ["AT111", "AT112", "AT113", "AT121", "AT123", "AT126", "AT127", "AT221", "AT224", "AT225",
           "AT314", "AT315", "AT323"],
}
ALPS_MARGIN = 2000  # m


def _zones(var, country):
    """Zones of a country from the environment, by default those of all the regions."""
    default = ",".join(dict.fromkeys(c for r in REGIONS.values() for c in r.get(country, [])))
    return [z.strip().upper() for z in os.environ.get(var, default).split(",") if z.strip()]


# French departments whose data is used. Switzerland always has priority: French
# data only fills the parts of a tile outside Switzerland.
FRANCE_DEPTS = [d.zfill(2) for d in _zones("FRANCE_DEPTS", "fr")]

# Italian zones whose data is used: provinces by their ISTAT abbreviation (AO, VB...),
# or GP, the Piedmont side of the Gran Paradiso (its municipalities in the province of
# Turin, for a map of the massif without the rest of the province).
ITALY_ZONES = _zones("ITALY_ZONES", "it")
GRAN_PARADISO = ["Ceresole Reale", "Locana", "Noasca", "Ribordone", "Ronco Canavese", "Valprato Soana"]

# Austrian, German and Spanish zones, by their NUTS 3 code (Eurostat), and Andorra (AD)
AUSTRIA_ZONES = _zones("AUSTRIA_ZONES", "at")
GERMANY_ZONES = _zones("GERMANY_ZONES", "de")
SPAIN_ZONES = _zones("SPAIN_ZONES", "es")
ANDORRA_ZONES = _zones("ANDORRA_ZONES", "ad")
# Countries mapped from OpenStreetMap, in priority order (after Switzerland and France)
OSM_ZONES = {"it": ITALY_ZONES, "at": AUSTRIA_ZONES, "de": GERMANY_ZONES, "es": SPAIN_ZONES, "ad": ANDORRA_ZONES}


def region_spec(region: str) -> str:
    """Coverage spec of a region, e.g. "canton:JU,NE+dept:25,39"."""
    kinds = {"ch": "canton", "fr": "dept"}
    return "+".join(f"{kinds.get(c, c)}:{','.join(codes)}" for c, codes in REGIONS[region].items())


# Coverage aliases: the regions. A region leaves out the tiles of the regions before it,
# so that the maps of the regions never share a tile and can all be installed together.
ALIASES = {name: region_spec(name) for name in REGIONS}

STAC = "https://data.geo.admin.ch/api/stac/v0.9"
IGN_DOWNLOAD = "https://data.geopf.fr/telechargement"
GEO_API_GOUV = "https://geo.api.gouv.fr"
ISTAT_BOUNDARIES = "https://www.istat.it/storage/cartografia/confini_amministrativi/generalizzati/2025/Limiti01012025_g.zip"
TINITALY = "https://tinitaly.pi.ingv.it/data_1.1"
GEOFABRIK = "https://download.geofabrik.de"
GISCO = "https://gisco-services.ec.europa.eu/distribution/v2"
AUSTRIA_DGM = "https://gis.ktn.gv.at/OGD/Geographie_Planung/ogd-10m-at.zip"
BAVARIA_DGM1 = "https://download1.bayernwolke.de/a/dgm/dgm1"
SPAIN_MDT_WCS = "https://servicios.idee.es/wcs-inspire/mdt"
COPERNICUS_DEM = "https://copernicus-dem-30m.s3.amazonaws.com"
# Perimeter of the Alpine Convention, 2025 (Permanent Secretariat of the Alpine Convention,
# CC BY 4.0, doi:10.48784/VK93-8P54)
ALPS_PERIMETER = ("https://www.atlas.alpconv.org/geoserver/ows?service=WFS&version=1.0.0&request=GetFeature"
                  "&typeName=geonode:Alpine_Convention_Perimeter_2025&outputFormat=application/json&srsName=EPSG:4326")
OVERPASS = "https://overpass-api.de/api/interpreter"
CAMPTOCAMP_API = "https://api.camptocamp.org"
USER_AGENT = "swisstopo-garmin (https://github.com/dustag/garmin-swisstopo)"
GEOADMIN_API = "https://api3.geo.admin.ch/rest/services/api/MapServer"
SOURCES = {
    "tlm3d": "https://data.geo.admin.ch/ch.swisstopo.swisstlm3d/swisstlm3d_2026-02/swisstlm3d_2026-02_2056_5728.gpkg.zip",
    "skitouren": "https://data.geo.admin.ch/ch.swisstopo-karto.skitouren/skitouren/skitouren_2056.gpkg.zip",
    "schneeschuh": "https://data.geo.admin.ch/ch.swisstopo-karto.schneeschuhrouten/schneeschuhrouten/schneeschuhrouten_2056.gpkg.zip",
}
# Wildlife quiet zones / protection areas and boundaries are queried from the geo.admin API
