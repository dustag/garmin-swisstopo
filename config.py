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
ALTI_IT_DIR = DOWNLOAD_DIR / "tinitaly_5m"  # TINITALY reprojected to LV95, 5 m, one file per km2
WORK_DIR = DATA_DIR / "work"
TILES_DIR = WORK_DIR / "tiles"             # per-tile intermediates, shared by all coverages
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", DATA_DIR / "output")).expanduser()
TOOLS_DIR = Path(os.environ.get("TOOLS_DIR", REPO_DIR / "tools")).expanduser()

# Java: JAVA_EXE, else the runtime bundled with the packaged application, else java from the PATH
_BUNDLED_JAVA = REPO_DIR / "jre" / "bin" / ("java.exe" if os.name == "nt" else "java")
JAVA = os.environ.get("JAVA_EXE") or (str(_BUNDLED_JAVA) if _BUNDLED_JAVA.exists() else "java")
JAVA_MAX_HEAP = os.environ.get("JAVA_MAX_HEAP", "4g")

# Coverage to build: an area name, "switzerland", "canton:VS[,VD...]", "dept:74[,73...]"
# (French departments), "it:AO[,GP...]" (Italian zones), "it" (all ITALY_ZONES) or "bbox:E0,N0,E1,N1" (LV95 metres); several can be
# combined with "+", e.g. "canton:VS+dept:74". Can be overridden with --coverage.
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
# Combined coverages ("a+b"): family id = 7000 + 2 * (stable hash of the spec % 1000)
COMBINED_FAMILY_ID = 7000
FAMILY_NAME = "Swisstopo"

# Label language: fr, de, it or en. Place names always stay in their official local form.
LANG = os.environ.get("LANG_LABELS", "fr").lower()
if LANG not in ("fr", "de", "it", "en"):
    raise ValueError(f"LANG_LABELS must be fr, de, it or en (got {LANG!r})")

# French departments whose data is used. Switzerland always has priority: French
# data only fills the parts of a tile outside Switzerland.
FRANCE_DEPTS = [d.strip() for d in os.environ.get("FRANCE_DEPTS", "74").split(",") if d.strip()]

# Italian zones whose data is used: provinces by their ISTAT abbreviation (AO, VB...)
# or GP, the Piedmont side of the Gran Paradiso (its municipalities in the province
# of Turin). The default covers the provinces bordering Switzerland and the whole
# Gran Paradiso. Switzerland and the French departments have priority.
ITALY_ZONES = [z.strip().upper() for z in os.environ.get("ITALY_ZONES", "AO,VB,VA,CO,SO,BZ,GP").split(",")
               if z.strip()]
GRAN_PARADISO = ["Ceresole Reale", "Locana", "Noasca", "Ribordone", "Ronco Canavese", "Valprato Soana"]

STAC = "https://data.geo.admin.ch/api/stac/v0.9"
IGN_DOWNLOAD = "https://data.geopf.fr/telechargement"
GEO_API_GOUV = "https://geo.api.gouv.fr"
ISTAT_BOUNDARIES = "https://www.istat.it/storage/cartografia/confini_amministrativi/generalizzati/2025/Limiti01012025_g.zip"
TINITALY = "https://tinitaly.pi.ingv.it/data_1.1"
GEOFABRIK = "https://download.geofabrik.de/europe/italy"
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
