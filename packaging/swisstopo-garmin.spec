# PyInstaller recipe of the application, run by build_app.py (which sets APP_VERSION).
# The Java runtime and mkgmap are copied into the application afterwards.
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
APP = "swisstopo-garmin"

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    # GDAL and PROJ data of the wheels (osmconf.ini for the Italian OpenStreetMap extracts...)
    datas=[(str(ROOT / "zones.json"), ".")] + collect_data_files("pyogrio") + collect_data_files("rasterio"),
    # Started by name from launcher.py; compiled modules imported from other compiled modules
    hiddenimports=["gui", "download", "build"] + collect_submodules("pyogrio") + collect_submodules("rasterio"),
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [("u", None, "OPTION")],   # unbuffered output, for the window's log
    exclude_binaries=True,
    name=APP,
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name=APP)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP}.app",
        bundle_identifier="io.github.dustag.garmin-swisstopo",
        version=os.environ.get("APP_VERSION", "0"),
        info_plist={"NSHighResolutionCapable": True, "LSApplicationCategoryType": "public.app-category.travel"},
    )
