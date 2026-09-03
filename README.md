# DOSCAR / COHP / COOP Plotter (desktop app)

A downloadable, offline desktop app for visualizing VASP/LOBSTER bonding
and electronic-structure data. It combines two web tools — the DOS plotter
from [doscar-gui](https://github.com/EmilJaffal/doscar-gui) and the
bonding-analysis plotter from
[cohp-coop-gui](https://github.com/EmilJaffal/cohp-coop-gui) — into one
native app for Mac and Windows, switchable from a dropdown in the top-left
corner: no browser, no server to run, no Python install required by the end
user. Those two web tools are now considered legacy/precursor projects —
this app is where active development happens going forward.

> **Testing status:** this app has so far only actually been *run* on
> **macOS**. [CI](../../actions) builds both platforms on every push and
> confirms the Windows `.exe` packages cleanly with PyInstaller, but no one
> has yet launched it on a real Windows machine to confirm the window opens
> and renders correctly — treat it as untested until that happens (see
> [HOW_TO_OPEN.md](HOW_TO_OPEN.md) and the note about WebView2 there).

## For users: install and run

> New to this? [HOW_TO_OPEN.md](HOW_TO_OPEN.md) is a plain-language,
> no-jargon walkthrough for opening the app on Mac or Windows — it's also
> bundled inside every build (as "How To Open.txt" next to the app/exe), so
> it travels along whenever the app is shared with someone else.

1. Download the build for your platform from the project's
   [Releases page](../../releases) (or from your CI artifacts if you're
   building yourself — see below):
   - **macOS**: `DOSCAR-Plotter-mac.dmg` → open it, drag the app into
     Applications, then launch it from there or Spotlight.
   - **Windows**: `DOSCAR Plotter-windows.zip` → unzip it anywhere, then run
     the `.exe` inside the extracted folder.
2. The app opens its own window. Use the dropdown at the top left (reads
   "DOSCAR Plotter" by default) to switch between the two tools:
   - **DOSCAR Plotter**: upload a ZIP containing a `POSCAR` and a `DOSCAR`
     (the folder inside the ZIP should be named after the compound, e.g.
     `Gd10RuCd3/`), or click **Load demo file**.
   - **COHP/COOP Plotter**: upload a ZIP containing `COHPCAR.lobster`
     and/or `COOPCAR.lobster` (folder named after the compound, e.g.
     `CeCoAl4/`), or click **Load demo file**.
3. Everything runs locally on your machine; no data leaves your computer.

**First-launch warnings are expected and safe to dismiss** — these builds
aren't code-signed:
- macOS (Gatekeeper): right-click the app → **Open** → **Open** again.
- Windows (SmartScreen): click **More info** → **Run anyway**.
- Windows only: the app window is rendered with Microsoft Edge WebView2,
  which ships with Windows 10/11 by default. If the window comes up blank,
  install the runtime from
  <https://developer.microsoft.com/microsoft-edge/webview2/>.

## What's the same as the original web tools

All of the original functionality carries over exactly, for both tools:

- DOSCAR Plotter: ISPIN=1 / ISPIN=2 (spin-polarized) support, all LORBIT
  variants, per-atom orbital selection and coloring, legend reordering,
  axis/legend-position controls, title/tick-label toggles, Mendeleev-ordered
  legend, total-DOS-as-sum-of-atoms convention.
- COHP/COOP Plotter: parses `COHPCAR.lobster` / `COOPCAR.lobster`, per-pair
  color and visibility, ICOHP/ICOOP overlay per pair, independent axis and
  legend-position controls for each of the two plots, auto-scaled x-ranges
  on upload.
- Both: high-resolution PNG export via Kaleido.

## What's different

- **It's a native app**, not a web page — built with [pywebview](https://pywebview.flowrl.com/)
  hosting the same Dash/Plotly logic as the two original tools, packaged
  into a standalone `.app` / `.exe` with [PyInstaller](https://pyinstaller.org/)
  so end users don't need Python, pip, or a terminal.
- **One app, two tools.** A dropdown in the top-left corner (where the app
  name is) switches between **DOSCAR Plotter** and **COHP/COOP Plotter**.
  Both stay loaded at once — switching is instant and doesn't lose either
  tool's uploaded data or settings.
- **Redesigned interface**: a sidebar (Data / axis / display / export cards)
  next to the plot(s) and the per-atom or per-pair table, a light/dark theme
  toggle (persisted per-user), and a refreshed visual style throughout
  ([assets/style.css](assets/style.css)). The plots themselves are untouched
  — still rendered on a white background so exported PNGs look exactly like
  the original tools' output.
- **Writable data lives outside the app bundle.** The DOSCAR side extracts
  uploads to a per-user app-support folder (`~/Library/Application
  Support/DOSCAR Plotter` on macOS, `%APPDATA%\DOSCAR Plotter` on Windows)
  instead of next to the app itself, since installed apps usually live in a
  read-only location (`/Applications`, `Program Files`). The COHP/COOP side
  never touches disk at all — it parses the uploaded ZIP fully in memory.
- Runs on a dynamically chosen local port and only binds to `127.0.0.1` —
  no fixed port conflicts, nothing reachable from the network.

## Repository layout

```
HOW_TO_OPEN.md            Plain-language open/install guide, bundled into every build
app.py                    Dash app: layout + callbacks for both tools (the UI and its logic)
desktop.py                Desktop entry point: runs app.py's server + opens the native window
src/doscar.py             DOSCAR/POSCAR parsing and Plotly figure construction
src/cohp_coop.py          COHPCAR/COOPCAR parsing and Plotly figure construction
assets/                   CSS, icons served by Dash (also bundled into the packaged app)
resources/                Demo ZIPs (DOSCAR + COHP/COOP) bundled into the packaged app
packaging/
  doscar.spec              PyInstaller build spec (used by both platforms)
  make_icons.py             Regenerates packaging/icon.icns and packaging/icon.ico
  icon.icns, icon.ico       Committed app icons (regenerate only if the design changes)
build_mac.sh               Build the macOS .app + .dmg (run on a Mac)
build_windows.bat          Build the Windows .exe + .zip (run on Windows)
.github/workflows/build.yml CI: builds both platforms on every push/PR, attaches
                            to a GitHub Release when you push a `v*` tag
```

## For developers

### Run it locally (no packaging)

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python desktop.py                # opens the native window
# — or, to iterate in a browser with Dash's dev reload instead —
python app.py                    # then open http://127.0.0.1:8050
```

### Build the standalone app yourself

PyInstaller does not cross-compile, so build on the OS you're targeting (or
let CI do both — see below).

```bash
# macOS
./build_mac.sh
# → dist/DOSCAR Plotter.app and dist/DOSCAR-Plotter-mac.dmg

# Windows (from cmd or PowerShell)
build_windows.bat
# → dist\DOSCAR Plotter\ and dist\DOSCAR Plotter-windows.zip
```

Both scripts create their own build virtualenv, install
`requirements-build.txt`, and run PyInstaller against
[packaging/doscar.spec](packaging/doscar.spec). The bundle is sizable
(several hundred MB) because Kaleido ships its own headless-Chromium binary
for PNG export — that's expected.

### Building both platforms via CI

Push to `main` (or open a PR) and [.github/workflows/build.yml](.github/workflows/build.yml)
builds both the macOS and Windows app as workflow artifacts. Push a tag like
`v1.0.0` and it also publishes both to a GitHub Release automatically.

### Regenerating the app icon

Only needed if you change the icon design:

```bash
pip install pillow
python packaging/make_icons.py
```

This overwrites `packaging/icon.icns` (macOS only — needs `iconutil`, which
ships with Xcode Command Line Tools) and `packaging/icon.ico` (any OS with
Pillow installed).

## License

MIT — see [LICENSE](LICENSE).
