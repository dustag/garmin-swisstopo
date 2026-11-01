"""Shared configuration for the Swisstopo -> Garmin (.img) pipeline.

Machine-specific paths are read from a `.env` file (see `.env.example`).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

REPO_DIR = Path(__file__).resolve().parent
load_dotenv(REPO_DIR / ".env")

# Large data (~16 GB) lives outside the repository
DATA_DIR = Path(os.environ.get("DATA_DIR", Path.home() / "swisstopo-data")).expanduser()
DOWNLOAD_DIR = DATA_DIR / "download"
WORK_DIR = DATA_DIR / "work"
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", DATA_DIR / "output")).expanduser()
TOOLS_DIR = Path(os.environ.get("TOOLS_DIR", REPO_DIR / "tools")).expanduser()

JAVA = os.environ.get("JAVA_EXE", "java")
JAVA_MAX_HEAP = os.environ.get("JAVA_MAX_HEAP", "4g")

# Areas in LV95 (EPSG:2056): (E min, N min, E max, N max) in metres
ZONES = {
    # Les Monts Telliers from the Grand-St-Bernard tunnel car park
    "telliers": (2_574_000, 1_079_000, 2_584_000, 1_088_000),
    # Village of Chavornay (VD) and its municipality, for testing on the plain
    "chavornay": (2_531_000, 1_170_000, 2_539_000, 1_177_000),
}
ZONE = os.environ.get("ZONE", "telliers")
BBOX = ZONES[ZONE]

# Label language: fr, de, it, rm (Romansh) or en. Place names always stay in
# their official local form; source attributes without Romansh fall back to German.
LANG = os.environ.get("LANG_LABELS", "fr").lower()
if LANG not in ("fr", "de", "it", "rm", "en"):
    raise ValueError(f"LANG_LABELS must be fr, de, it, rm or en (got {LANG!r})")
DATA_LANG = "de" if LANG == "rm" else LANG

# Garmin identifiers: family ids and map ids must be unique among the maps on
# the device, so each area gets its own pair (base, winter) derived from its
# position in ZONES. Append new areas at the end to keep existing ids stable.
ZONE_INDEX = list(ZONES).index(ZONE)
FAMILY_ID = 6520 + 2 * ZONE_INDEX          # base map; winter overlay = FAMILY_ID + 1
FAMILY_NAME = "Swisstopo CAS"
MAP_ID = 65200000 + 10 * ZONE_INDEX        # base map; winter overlay = MAP_ID + 1

STAC = "https://data.geo.admin.ch/api/stac/v0.9"
SOURCES = {
    "tlm3d": "https://data.geo.admin.ch/ch.swisstopo.swisstlm3d/swisstlm3d_2026-02/swisstlm3d_2026-02_2056_5728.gpkg.zip",
    "skitouren": "https://data.geo.admin.ch/ch.swisstopo-karto.skitouren/skitouren/skitouren_2056.gpkg.zip",
    "schneeschuh": "https://data.geo.admin.ch/ch.swisstopo-karto.schneeschuhrouten/schneeschuhrouten/schneeschuhrouten_2056.gpkg.zip",
}
# Wildlife quiet zones / protection areas are queried from the geo.admin API (see build.py)
