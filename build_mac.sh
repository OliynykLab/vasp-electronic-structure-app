#!/usr/bin/env bash
# Build the macOS .app (and a .dmg for distribution) on a Mac.
# Usage: ./build_mac.sh
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR=".build-venv-mac"
APP_NAME="DOSCAR Plotter"

echo "==> Setting up build environment ($VENV_DIR)"
"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r requirements-build.txt

if [ ! -f "packaging/icon.icns" ]; then
  echo "==> Generating app icon"
  "$VENV_DIR/bin/python" packaging/make_icons.py
fi

echo "==> Running PyInstaller"
rm -rf build dist
"$VENV_DIR/bin/pyinstaller" packaging/doscar.spec --noconfirm --clean

APP_PATH="dist/${APP_NAME}.app"
if [ ! -d "$APP_PATH" ]; then
  echo "Build did not produce $APP_PATH" >&2
  exit 1
fi

echo "==> Patching kaleido's bundled wrapper script"
# kaleido 0.2.1 ships a bundled executable/kaleido wrapper shell script with
# two unquoted variable expansions (`cd $DIR` and `./bin/kaleido $@`) that
# word-split on spaces -- breaking Save-as-PNG the moment any ancestor path
# contains one, which "DOSCAR Plotter.app" always does. Patch every real
# copy PyInstaller creates (Contents/Frameworks/... is normally just a
# symlink to Contents/Resources/..., so `-type f` naturally skips it and
# patches the one real file underneath).
while IFS= read -r -d '' script; do
  sed -i '' 's/^cd \$DIR$/cd "$DIR"/; s#^\./bin/kaleido \$@$#./bin/kaleido "$@"#' "$script"
done < <(find "$APP_PATH" -type f -path '*/kaleido/executable/kaleido' -print0)

echo "==> Building disk image"
DMG_PATH="dist/${APP_NAME// /-}-mac.dmg"
rm -f "$DMG_PATH"

# Stage the .app alongside an Applications shortcut (the standard
# drag-to-install layout) and the plain-language open/install guide, so
# both are visible the moment someone opens the DMG.
STAGE_DIR="$(mktemp -d)"
trap 'rm -rf "$STAGE_DIR"' EXIT
cp -R "$APP_PATH" "$STAGE_DIR/"
ln -s /Applications "$STAGE_DIR/Applications"
if [ -f "HOW_TO_OPEN.md" ]; then
  cp "HOW_TO_OPEN.md" "$STAGE_DIR/How To Open.txt"
fi

hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE_DIR" -ov -format UDZO "$DMG_PATH"

echo
echo "Done."
echo "  App: $APP_PATH"
echo "  DMG: $DMG_PATH"
echo
echo "Note: this build is not code-signed or notarized. On first launch,"
echo "macOS Gatekeeper will warn that it's from an unidentified developer —"
echo "right-click the app and choose Open once to allow it (see HOW_TO_OPEN.md,"
echo "which is also bundled inside the DMG as 'How To Open.txt')."
