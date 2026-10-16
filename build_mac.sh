#!/usr/bin/env bash
# Build the macOS .app (and a .dmg for distribution) on a Mac.
# Usage: ./build_mac.sh
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR=".build-venv-mac"
APP_NAME="VASP Plotter"
ARTIFACT_SLUG="vasp-plotter-app"

echo "==> Setting up build environment ($VENV_DIR)"
# Reuse an existing venv rather than re-running `venv` over it: re-creating
# it with a different interpreter than the one it was made from rewrites
# pyvenv.cfg and leaves the venv broken.
if [ ! -x "$VENV_DIR/bin/python" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r requirements-build.txt

if [ ! -f "packaging/icon.icns" ]; then
  echo "==> Generating app icon"
  "$VENV_DIR/bin/python" packaging/make_icons.py
fi

echo "==> Running PyInstaller"
rm -rf build dist
"$VENV_DIR/bin/pyinstaller" packaging/vasp-plotter-app.spec --noconfirm --clean

APP_PATH="dist/${APP_NAME}.app"
if [ ! -d "$APP_PATH" ]; then
  echo "Build did not produce $APP_PATH" >&2
  exit 1
fi

echo "==> Patching kaleido's bundled wrapper script"
# kaleido 0.2.1 ships a bundled executable/kaleido wrapper shell script with
# two unquoted variable expansions (`cd $DIR` and `./bin/kaleido $@`) that
# word-split on spaces -- breaking Save-as-PNG the moment any ancestor path
# contains one, which "VASP Plotter.app" always does. Patch every real
# copy PyInstaller creates (Contents/Frameworks/... is normally just a
# symlink to Contents/Resources/..., so `-type f` naturally skips it and
# patches the one real file underneath).
while IFS= read -r -d '' script; do
  sed -i '' 's/^cd \$DIR$/cd "$DIR"/; s#^\./bin/kaleido \$@$#./bin/kaleido "$@"#' "$script"
done < <(find "$APP_PATH" -type f -path '*/kaleido/executable/kaleido' -print0)

echo "==> Signing"
# PyInstaller's own ad-hoc signature can come out broken ("code has no
# resources but signature indicates they must be present") when the repo
# lives on an iCloud-synced Desktop, which keeps re-adding extended
# attributes inside dist/. Sign a copy in a temp dir outside iCloud and put
# that back in dist/. Signing has to happen *after* the kaleido patch above,
# or the rewritten file would invalidate it.
SIGN_DIR="$(mktemp -d)"
STAGE_DIR="$(mktemp -d)"
trap 'rm -rf "$SIGN_DIR" "$STAGE_DIR"' EXIT
ditto --norsrc --noextattr "$APP_PATH" "$SIGN_DIR/${APP_NAME}.app"
xattr -cr "$SIGN_DIR/${APP_NAME}.app"
codesign -s - --force --deep "$SIGN_DIR/${APP_NAME}.app"
codesign -v "$SIGN_DIR/${APP_NAME}.app"
rm -rf "$APP_PATH"
ditto --norsrc --noextattr "$SIGN_DIR/${APP_NAME}.app" "$APP_PATH"

echo "==> Building disk image"
DMG_PATH="dist/${ARTIFACT_SLUG}-mac.dmg"
rm -f "$DMG_PATH"

# Stage the .app alongside an Applications shortcut (the standard
# drag-to-install layout) and the plain-language open/install guide, so
# both are visible the moment someone opens the DMG.
ditto --norsrc --noextattr "$SIGN_DIR/${APP_NAME}.app" "$STAGE_DIR/${APP_NAME}.app"
ln -s /Applications "$STAGE_DIR/Applications"
if [ -f "HOW_TO_OPEN.md" ]; then
  cp "HOW_TO_OPEN.md" "$STAGE_DIR/How To Open.txt"
fi

hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE_DIR" -ov -format UDZO "$DMG_PATH"

# Install the signed copy locally (replacing any older one). Set
# NO_INSTALL=1 to only build into dist/.
INSTALLED=""
if [ "${NO_INSTALL:-0}" != "1" ]; then
  echo "==> Installing to /Applications"
  rm -rf "/Applications/${APP_NAME}.app"
  ditto --norsrc --noextattr "$SIGN_DIR/${APP_NAME}.app" "/Applications/${APP_NAME}.app"
  /System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister \
    -f "/Applications/${APP_NAME}.app" 2>/dev/null || true
  INSTALLED="/Applications/${APP_NAME}.app"
fi

echo
echo "Done."
echo "  App: $APP_PATH"
echo "  DMG: $DMG_PATH"
if [ -n "$INSTALLED" ]; then
  echo "  Installed: $INSTALLED"
fi
echo
echo "Note: this build is not code-signed or notarized. On first launch,"
echo "macOS Gatekeeper will block a downloaded copy — allow it once via System"
echo "Settings → Privacy & Security → Open Anyway (see HOW_TO_OPEN.md, which is"
echo "also bundled inside the DMG as 'How To Open.txt')."
