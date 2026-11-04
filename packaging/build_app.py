"""Build the standalone application for the current platform.

    python packaging/build_app.py

Windows: dist/swisstopo-garmin-<version>-windows-x64.zip, a folder to unzip anywhere,
with swisstopo-garmin.exe. macOS: dist/swisstopo-garmin-<version>-macos-<arch>.dmg,
with swisstopo-garmin.app. Nothing else to install: the application holds Python, the
libraries, a minimal Java runtime made with jlink, and mkgmap.

Requirements: the packages of requirements.txt and packaging/requirements.txt, and a JDK
21 or newer for jlink (JAVA_HOME, jlink in the PATH, or JAVA_EXE of .env). The version
is the latest one of CHANGELOG.md. PyInstaller does not cross-compile: build each
platform on itself (the GitHub workflow .github/workflows/package.yml does both).
"""
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config  # noqa: E402

APP = "swisstopo-garmin"

# Intermediate files stay out of the repository: synced folders (OneDrive...) lock them
WORK = Path(os.environ.get("APP_BUILD_DIR", Path(tempfile.gettempdir()) / f"{APP}-build"))
BUNDLES = WORK / "dist"
DIST = ROOT / "dist"   # final archives
MKGMAP_URL = "https://www.mkgmap.org.uk/download/mkgmap-latest.zip"
EXE = ".exe" if os.name == "nt" else ""


def version() -> str:
    return re.search(r"^## \[(\d+\.\d+\.\d+)\]", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), re.M)[1]


def jdk_tool(name: str) -> str:
    """jlink or jdeps of the JDK."""
    candidates = []
    if os.environ.get("JAVA_HOME"):
        candidates.append(Path(os.environ["JAVA_HOME"]) / "bin" / f"{name}{EXE}")
    if found := shutil.which(name):
        candidates.append(Path(found))
    if os.environ.get("JAVA_EXE"):
        candidates.append(Path(os.environ["JAVA_EXE"]).with_name(f"{name}{EXE}"))
    for path in candidates:
        if path.is_file():
            return str(path)
    raise SystemExit(f"{name} not found: install a JDK 21+ and set JAVA_HOME")


def get_mkgmap() -> Path:
    """mkgmap, unpacked in WORK/tools/mkgmap-latest (the layout config.TOOLS_DIR expects)."""
    out = WORK / "tools" / "mkgmap-latest"
    if not next(out.glob("mkgmap-*/mkgmap.jar"), None):
        archive = WORK / "mkgmap-latest.zip"
        archive.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(MKGMAP_URL, headers={"User-Agent": config.USER_AGENT})
        with urllib.request.urlopen(req) as r, open(archive, "wb") as f:
            shutil.copyfileobj(r, f)
        with zipfile.ZipFile(archive) as z:
            z.extractall(out)
    jar = next(out.glob("mkgmap-*/mkgmap.jar"))
    print(f"mkgmap: {jar.parent.name}")
    return jar


def make_jre(jar: Path) -> Path:
    """Minimal Java runtime with the modules mkgmap and its libraries use."""
    jars = [str(jar)] + [str(p) for p in (jar.parent / "lib").glob("*.jar")]
    modules = subprocess.run([jdk_tool("jdeps"), "--print-module-deps", "--ignore-missing-deps", "--multi-release",
                              "base", *jars], check=True, capture_output=True, text=True).stdout.strip()
    jre = WORK / "jre"
    remove(jre)
    subprocess.run([jdk_tool("jlink"), "--add-modules", modules, "--strip-debug", "--no-man-pages",
                    "--no-header-files", "--compress=zip-6", "--output", str(jre)], check=True)
    print(f"Java runtime: {modules} ({size_mb(jre):.0f} MB)")
    return jre


def remove(path: Path):
    """Delete a folder, including the read-only files jlink makes on Windows."""
    def retry(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if path.exists():
        shutil.rmtree(path, onexc=retry)


def size_mb(path: Path) -> float:
    files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
    return sum(p.stat().st_size for p in files) / 1e6


def main():
    ver = version()
    print(f"{APP} {ver} for {sys.platform} {platform.machine()}")
    jar = get_mkgmap()
    jre = make_jre(jar)

    for previous in (BUNDLES / APP, BUNDLES / f"{APP}.app"):   # read-only runtime files stop PyInstaller
        remove(previous)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(BUNDLES),
                    "--workpath", str(WORK / "pyinstaller"), str(ROOT / "packaging" / f"{APP}.spec")],
                   check=True, env=os.environ | {"APP_VERSION": ver})

    # The runtime and mkgmap go next to the Python modules, where config.py looks for them
    if sys.platform == "darwin":
        bundle = BUNDLES / f"{APP}.app"
        internal = bundle / "Contents" / "Frameworks"
    else:
        bundle = BUNDLES / APP
        internal = bundle / "_internal"
    shutil.copytree(jre, internal / "jre", dirs_exist_ok=True)
    shutil.copytree(WORK / "tools", internal / "tools", dirs_exist_ok=True)

    DIST.mkdir(exist_ok=True)
    if sys.platform == "darwin":
        # Ad-hoc signature of the whole bundle, needed on Apple silicon after adding the runtime
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(bundle)], check=True)
        arch = "arm64" if platform.machine() == "arm64" else "x64"
        staging = WORK / "dmg"
        remove(staging)
        staging.mkdir(parents=True)
        shutil.copytree(bundle, staging / bundle.name, symlinks=True)
        (staging / "Applications").symlink_to("/Applications")
        package = DIST / f"{APP}-{ver}-macos-{arch}.dmg"
        package.unlink(missing_ok=True)
        subprocess.run(["hdiutil", "create", "-volname", APP, "-srcfolder", str(staging), "-format", "UDZO",
                        str(package)], check=True)
    else:
        package = DIST / f"{APP}-{ver}-windows-x64.zip"
        package.unlink(missing_ok=True)
        shutil.make_archive(str(package.with_suffix("")), "zip", BUNDLES, APP)
    print(f"-> {package} ({size_mb(package):.0f} MB, {size_mb(bundle):.0f} MB unpacked)")


if __name__ == "__main__":
    main()
