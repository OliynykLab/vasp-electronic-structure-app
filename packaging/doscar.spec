# PyInstaller spec for DOSCAR Plotter.
#
# Build from the repo root with:
#   pyinstaller packaging/doscar.spec --noconfirm --clean
#
# PyInstaller does not cross-compile: run this on macOS to get the .app and
# on Windows to get the .exe (see build_mac.sh / build_windows.bat, or the
# GitHub Actions workflow which builds both automatically).

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None

REPO_ROOT = Path(SPECPATH).parent
APP_NAME = "DOSCAR Plotter"

# These packages ship non-Python data (JS bundles, JSON schemas, or in
# kaleido's case an entire headless-Chromium binary) that PyInstaller's
# default import analysis won't pick up on its own.
datas = []
binaries = []
hiddenimports = []
for pkg in ("dash", "plotly", "kaleido", "webview"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

datas += [
    (str(REPO_ROOT / "assets"), "assets"),
    (str(REPO_ROOT / "resources"), "resources"),
]

icon_path = None
if sys.platform == "darwin":
    icon_candidate = REPO_ROOT / "packaging" / "icon.icns"
    if icon_candidate.exists():
        icon_path = str(icon_candidate)
elif sys.platform == "win32":
    icon_candidate = REPO_ROOT / "packaging" / "icon.ico"
    if icon_candidate.exists():
        icon_path = str(icon_candidate)

a = Analysis(
    [str(REPO_ROOT / "desktop.py")],
    pathex=[str(REPO_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=icon_path,
        bundle_identifier="com.emiljaffal.doscarplotter",
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": "1.0.0",
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.education",
        },
    )
