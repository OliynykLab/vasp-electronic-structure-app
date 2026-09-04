import base64
import math
import mimetypes
import os
import re
import shutil
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import dash
import numpy as np
import plotly.graph_objects as go
import plotly.io as pio
from dash import ALL, Dash, Input, Output, State, dcc, html
from dash.exceptions import PreventUpdate

from src.doscar import (
    classify_orbitals,
    parse_doscar_and_plot,
    read_atom_dos_blocks,
    read_doscar_header,
)
from src.cohp_coop import (
    DEFAULTS as COHP_DEFAULTS,
    auto_x_limits,
    build_bonding_figure,
    extract_unique_pairs,
)

pio.kaleido.scope.default_format = "png"
pio.kaleido.scope.default_width = 1200
pio.kaleido.scope.default_height = 800
pio.kaleido.scope.default_scale = 2

APP_NAME = "DOSCAR Plotter"

DEFAULTS = {
    "xmin": 0,
    "xmax": 28,
    "ymin": -8,
    "ymax": 2,
    "legend_y": 0.26,
}


# --------------------------------------------------------------------------
# Path helpers — a packaged desktop app (PyInstaller bundle sitting inside
# /Applications or Program Files) is typically read-only and lives in a
# different place each install, so bundled resources and user data both need
# resolving at runtime rather than assuming a fixed on-disk layout.
# --------------------------------------------------------------------------

def resource_path(*parts):
    """Resolve a path to a bundled resource, in dev or in a frozen build."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, *parts)


def get_app_data_dir():
    """A writable, per-user directory for scratch files (uploads, extraction)."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    else:
        base = Path.home() / f".{APP_NAME.lower().replace(' ', '-')}"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_downloads_dir():
    """The user's actual Downloads folder, saved to directly.

    Routing plot exports through the browser-style download flow
    (dcc.Download, a blob: URL) is unreliable inside a WKWebView desktop
    window — the suggested filename doesn't always survive the trip, which
    is why saved plots could show up named "Unknown". Writing the PNG
    straight to disk from Python sidesteps that entirely.
    """
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
            ) as key:
                path, _ = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
            downloads = Path(os.path.expandvars(path))
        except Exception:
            downloads = Path.home() / "Downloads"
    else:
        downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    return downloads


def unique_download_path(directory, filename):
    """`directory / filename`, or `name (1).ext`, `name (2).ext`, ... if that
    already exists — mirrors the "don't silently overwrite" behavior a
    browser's own download manager gives you for free."""
    path = directory / filename
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    counter = 1
    while True:
        candidate = directory / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


app = Dash(
    __name__,
    assets_folder=resource_path("assets"),
    title=APP_NAME,
    update_title=None,
)
server = app.server

# Blocking inline script (runs before Dash renders) avoids a flash of the
# wrong theme on load by applying any previously saved preference immediately.
app.index_string = """<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <script>
            (function () {
                try {
                    var saved = window.localStorage.getItem('doscar-theme');
                    if (saved === 'light' || saved === 'dark') {
                        document.documentElement.setAttribute('data-theme', saved);
                    }
                } catch (e) {}
            })();
        </script>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>"""


def labeled_number(label, input_id, value, **kwargs):
    return html.Div(
        [
            html.Label(label, className="field-label"),
            dcc.Input(id=input_id, type="number", value=value, className="num-input", **kwargs),
        ]
    )


app.layout = html.Div(
    id="app-shell",
    className="app-shell",
    children=[
        html.Header(
            className="topbar",
            children=[
                html.Div(
                    className="brand",
                    children=[
                        html.Div(
                            className="brand-mark",
                            children=html.Img(
                                src=app.get_asset_url("icon.svg"),
                                style={"width": "20px", "height": "20px"},
                            ),
                        ),
                        html.Div(
                            className="brand-text",
                            children=[
                                dcc.Dropdown(
                                    id="app-mode",
                                    className="mode-select",
                                    options=[
                                        {"label": "DOSCAR Plotter", "value": "doscar"},
                                        {"label": "COHP/COOP Plotter", "value": "cohp"},
                                    ],
                                    value="doscar",
                                    clearable=False,
                                    searchable=False,
                                ),
                                html.Span(id="mode-subtitle", className="brand-subtitle"),
                            ],
                        ),
                    ],
                ),
                html.Div(
                    className="topbar-actions",
                    children=[
                        html.Div(id="folder-badge-display", className="folder-badge"),
                        html.Button(
                            id="theme-toggle",
                            className="theme-toggle",
                            n_clicks=0,
                            title="Toggle light / dark theme",
                            children=[
                                html.Span("🌙", className="icon-moon"),
                                html.Span("☀️", className="icon-sun"),
                            ],
                        ),
                    ],
                ),
            ],
        ),
        html.Div(
            id="doscar-page",
            className="app-body",
            style={"display": "flex"},
            children=[
                html.Aside(
                    className="sidebar",
                    children=[
                        html.Section(
                            className="card",
                            children=[
                                html.H2("Data", className="card-title"),
                                dcc.Upload(
                                    id="upload-data",
                                    className="upload-dropzone",
                                    multiple=False,
                                    children=html.Div(
                                        [
                                            html.Span("📁", className="upload-icon"),
                                            html.Span("Upload ZIP file", className="upload-title"),
                                            html.Span(
                                                "POSCAR + DOSCAR, zipped together",
                                                className="upload-subtitle",
                                            ),
                                        ]
                                    ),
                                ),
                                html.Button(
                                    "Load demo file",
                                    id="demo-file",
                                    n_clicks=0,
                                    className="btn btn-secondary btn-block section-gap",
                                ),
                                html.Div(id="spin-message", className="status-box"),
                            ],
                        ),
                        html.Section(
                            className="card",
                            children=[
                                html.H2("Display", className="card-title"),
                                html.Div(
                                    dcc.Checklist(
                                        id="show-titles",
                                        options=[
                                            {"label": "Plot title", "value": "plot_title"},
                                            {"label": "X axis title", "value": "x_title"},
                                            {"label": "Y axis title", "value": "y_title"},
                                        ],
                                        value=["plot_title", "x_title", "y_title"],
                                        className="field-checklist",
                                    ),
                                    className="section-gap",
                                ),
                                html.Div(
                                    dcc.Checklist(
                                        id="show-axis-scale",
                                        options=[
                                            {"label": "Show X axis scale", "value": "x_scale"},
                                            {"label": "Show Y axis scale", "value": "y_scale"},
                                        ],
                                        value=["x_scale", "y_scale"],
                                        className="field-checklist",
                                    ),
                                    className="section-gap",
                                ),
                                html.Div(
                                    dcc.Checklist(
                                        id="display-spins",
                                        options=[
                                            {
                                                "label": "Display spins (up: right, down: left)",
                                                "value": "display_spins",
                                            },
                                        ],
                                        value=[],
                                        className="field-checklist",
                                    ),
                                    className="section-gap",
                                ),
                            ],
                        ),
                        html.Section(
                            className="card",
                            children=[
                                html.H2("Axes", className="card-title"),
                                labeled_number("X min", "xmin", DEFAULTS["xmin"]),
                                html.Div(
                                    labeled_number("X max", "xmax", DEFAULTS["xmax"]),
                                    className="section-gap",
                                ),
                                html.Div(
                                    labeled_number("Y min", "ymin", DEFAULTS["ymin"]),
                                    className="section-gap",
                                ),
                                html.Div(
                                    labeled_number("Y max", "ymax", DEFAULTS["ymax"]),
                                    className="section-gap",
                                ),
                                html.Div(
                                    labeled_number(
                                        "Legend Y position",
                                        "legend-y",
                                        DEFAULTS["legend_y"],
                                        min=0,
                                        max=1,
                                        step=0.01,
                                    ),
                                    className="section-gap",
                                ),
                                html.Button(
                                    "Reset axes",
                                    id="reset-axes",
                                    n_clicks=0,
                                    className="btn btn-ghost btn-block section-gap",
                                ),
                            ],
                        ),
                        html.Section(
                            className="card",
                            children=[
                                html.H2("Export", className="card-title"),
                                html.Button(
                                    "Save plot as PNG",
                                    id="save-plot",
                                    n_clicks=0,
                                    className="btn btn-primary btn-block",
                                ),
                                html.Div(id="save-confirmation", className="status-box status-success"),
                            ],
                        ),
                    ],
                ),
                html.Main(
                    className="plot-pane",
                    children=[
                        html.Section(
                            className="card plot-card",
                            children=[
                                html.Div(
                                    dcc.Graph(
                                        id="dos-plot",
                                        className="dos-graph",
                                        config={
                                            "displaylogo": False,
                                            "modeBarButtonsToRemove": [
                                                "select2d",
                                                "lasso2d",
                                                "autoScale2d",
                                                # Plotly's own PNG download goes through the same
                                                # blob-download path that names files "Unknown" in
                                                # this desktop window; use Save Plot instead.
                                                "toImage",
                                            ],
                                        },
                                    ),
                                    className="plot-frame",
                                )
                            ],
                        ),
                    ],
                ),
                html.Aside(
                    className="atomic-pane",
                    children=[
                        html.Section(
                            className="card",
                            children=[
                                html.Div(
                                    className="card-header-row",
                                    children=[
                                        html.H2("Atomic contributions", className="card-title"),
                                        html.P(
                                            "Select orbitals and colors per atom type. "
                                            "Use the arrows to reorder the legend.",
                                            className="card-hint",
                                        ),
                                    ],
                                ),
                                html.Div(
                                    id="atomic-contributions-container",
                                    children=html.Div(
                                        "Upload a ZIP file or load the demo file to get started.",
                                        className="empty-hint",
                                    ),
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        ),
        html.Div(id="folder-name", style={"display": "none"}),
        html.Div(
            id="cohp-page",
            className="app-body",
            style={"display": "none"},
            children=[
                html.Aside(
                    className="sidebar",
                    children=[
                        html.Section(
                            className="card",
                            children=[
                                html.H2("Data", className="card-title"),
                                dcc.Upload(
                                    id="cc-upload-data",
                                    className="upload-dropzone",
                                    multiple=False,
                                    children=html.Div(
                                        [
                                            html.Span("📁", className="upload-icon"),
                                            html.Span("Upload ZIP file", className="upload-title"),
                                            html.Span(
                                                "COHPCAR.lobster and/or COOPCAR.lobster",
                                                className="upload-subtitle",
                                            ),
                                        ]
                                    ),
                                ),
                                html.Button(
                                    "Load demo file",
                                    id="cc-demo-file",
                                    n_clicks=0,
                                    className="btn btn-secondary btn-block section-gap",
                                ),
                            ],
                        ),
                        html.Section(
                            className="card",
                            children=[
                                html.H2("COHP", className="card-title"),
                                html.Div(
                                    className="field-row",
                                    children=[
                                        labeled_number("X min", "cc-xmin-cohp", None),
                                        labeled_number("X max", "cc-xmax-cohp", None),
                                    ],
                                ),
                                html.Div(
                                    className="field-row section-gap",
                                    children=[
                                        labeled_number("Y min", "cc-ymin-cohp", COHP_DEFAULTS["ymin"]),
                                        labeled_number("Y max", "cc-ymax-cohp", COHP_DEFAULTS["ymax"]),
                                    ],
                                ),
                                html.Div(
                                    className="field-row section-gap",
                                    children=[
                                        labeled_number(
                                            "Legend X", "cc-legend-x-cohp", COHP_DEFAULTS["legend_x"],
                                            min=0, max=1, step=0.01,
                                        ),
                                        labeled_number(
                                            "Legend Y", "cc-legend-y-cohp", COHP_DEFAULTS["legend_y"],
                                            min=0, max=1, step=0.01,
                                        ),
                                    ],
                                ),
                                html.Div(
                                    dcc.Checklist(
                                        id="cc-show-titles-cohp",
                                        options=[
                                            {"label": "Plot title", "value": "plot_title"},
                                            {"label": "X axis title", "value": "x_title"},
                                            {"label": "Y axis title", "value": "y_title"},
                                        ],
                                        value=["plot_title", "x_title", "y_title"],
                                        className="field-checklist",
                                    ),
                                    className="section-gap",
                                ),
                                html.Div(
                                    dcc.Checklist(
                                        id="cc-show-axis-scale-cohp",
                                        options=[
                                            {"label": "Show X axis scale", "value": "x_scale"},
                                            {"label": "Show Y axis scale", "value": "y_scale"},
                                        ],
                                        value=["x_scale", "y_scale"],
                                        className="field-checklist",
                                    ),
                                    className="section-gap",
                                ),
                            ],
                        ),
                        html.Section(
                            className="card",
                            children=[
                                html.H2("COOP", className="card-title"),
                                html.Div(
                                    className="field-row",
                                    children=[
                                        labeled_number("X min", "cc-xmin-coop", None),
                                        labeled_number("X max", "cc-xmax-coop", None),
                                    ],
                                ),
                                html.Div(
                                    className="field-row section-gap",
                                    children=[
                                        labeled_number("Y min", "cc-ymin-coop", COHP_DEFAULTS["ymin"]),
                                        labeled_number("Y max", "cc-ymax-coop", COHP_DEFAULTS["ymax"]),
                                    ],
                                ),
                                html.Div(
                                    className="field-row section-gap",
                                    children=[
                                        labeled_number(
                                            "Legend X", "cc-legend-x-coop", COHP_DEFAULTS["legend_x"],
                                            min=0, max=1, step=0.01,
                                        ),
                                        labeled_number(
                                            "Legend Y", "cc-legend-y-coop", COHP_DEFAULTS["legend_y"],
                                            min=0, max=1, step=0.01,
                                        ),
                                    ],
                                ),
                                html.Div(
                                    dcc.Checklist(
                                        id="cc-show-titles-coop",
                                        options=[
                                            {"label": "Plot title", "value": "plot_title"},
                                            {"label": "X axis title", "value": "x_title"},
                                            {"label": "Y axis title", "value": "y_title"},
                                        ],
                                        value=["plot_title", "x_title", "y_title"],
                                        className="field-checklist",
                                    ),
                                    className="section-gap",
                                ),
                                html.Div(
                                    dcc.Checklist(
                                        id="cc-show-axis-scale-coop",
                                        options=[
                                            {"label": "Show X axis scale", "value": "x_scale"},
                                            {"label": "Show Y axis scale", "value": "y_scale"},
                                        ],
                                        value=["x_scale", "y_scale"],
                                        className="field-checklist",
                                    ),
                                    className="section-gap",
                                ),
                            ],
                        ),
                        html.Section(
                            className="card",
                            children=[
                                html.H2("Export", className="card-title"),
                                html.Button(
                                    "Reset axes",
                                    id="cc-reset-axes",
                                    n_clicks=0,
                                    className="btn btn-ghost btn-block",
                                ),
                                html.Button(
                                    "Save COHP plot as PNG",
                                    id="cc-save-plot",
                                    n_clicks=0,
                                    className="btn btn-primary btn-block section-gap",
                                ),
                                html.Div(id="cc-save-confirmation", className="status-box status-success"),
                                html.Button(
                                    "Save COOP plot as PNG",
                                    id="cc-save-coop-plot",
                                    n_clicks=0,
                                    className="btn btn-primary btn-block section-gap",
                                ),
                                html.Div(id="cc-save-coop-confirmation", className="status-box status-success"),
                            ],
                        ),
                    ],
                ),
                html.Main(
                    className="plot-pane",
                    children=[
                        html.Div(
                            className="dual-plot-row",
                            children=[
                                html.Section(
                                    className="card plot-card",
                                    children=[
                                        html.Div(
                                            [
                                                html.Div(id="cc-cohp-warning", className="status-box status-warning"),
                                                dcc.Graph(
                                                    id="cc-cohp-plot",
                                                    className="dos-graph",
                                                    config={
                                        "displaylogo": False,
                                        "modeBarButtonsToRemove": ["toImage"],
                                    },
                                                ),
                                            ],
                                            className="plot-frame",
                                        )
                                    ],
                                ),
                                html.Section(
                                    className="card plot-card",
                                    children=[
                                        html.Div(
                                            [
                                                html.Div(id="cc-coop-warning", className="status-box status-warning"),
                                                dcc.Graph(
                                                    id="cc-coop-plot",
                                                    className="dos-graph",
                                                    config={
                                        "displaylogo": False,
                                        "modeBarButtonsToRemove": ["toImage"],
                                    },
                                                ),
                                            ],
                                            className="plot-frame",
                                        )
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
                html.Aside(
                    className="atomic-pane",
                    children=[
                        html.Section(
                            className="card",
                            children=[
                                html.Div(
                                    className="card-header-row",
                                    children=[
                                        html.H2("Element pairs", className="card-title"),
                                        html.P(
                                            "Choose which bonded pairs to plot, their color, and "
                                            "whether to overlay the integrated ICOHP/ICOOP curve.",
                                            className="card-hint",
                                        ),
                                    ],
                                ),
                                html.Div(
                                    id="cc-element-pair-table",
                                    children=html.Div(
                                        "Upload a ZIP file or load the demo file to get started.",
                                        className="empty-hint",
                                    ),
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        ),
        html.Div(id="cc-folder-name", style={"display": "none"}),
        dcc.Store(id="uploaded-contents"),
        dcc.Store(id="atom-defaults"),
        dcc.Store(id="spin-polarization"),
        dcc.Store(id="action-message-store"),
        dcc.Store(id="legend-order", data=[]),
        dcc.Store(id="cc-uploaded-contents"),
        dcc.Store(id="theme-store", storage_type="local"),
        html.Div(id="debug-message", style={"display": "none"}),
        html.Div(id="spin-polarization-status", style={"display": "none"}),
    ],
)


app.clientside_callback(
    """
    function(n_clicks) {
        if (!n_clicks) {
            return window.dash_clientside.no_update;
        }
        var root = document.documentElement;
        var current = root.getAttribute('data-theme') || 'light';
        var next = current === 'light' ? 'dark' : 'light';
        root.setAttribute('data-theme', next);
        try { window.localStorage.setItem('doscar-theme', next); } catch (e) {}
        return next;
    }
    """,
    Output("theme-store", "data"),
    Input("theme-toggle", "n_clicks"),
    prevent_initial_call=True,
)


@app.callback(
    Output("uploaded-contents", "data"),
    Output("folder-name", "children"),
    Output("atom-defaults", "data"),
    Input("upload-data", "contents"),
)
def store_uploaded_file(contents):
    if contents is None:
        return None, "", {}

    try:
        # Decode the uploaded content
        content_type, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)

        # Define paths for the ZIP file and extraction folder
        data_dir = get_app_data_dir()
        zip_path = os.path.join(data_dir, 'uploaded_folder.zip')
        extracted_folder = os.path.join(data_dir, 'uploaded_folder')

        # Clear the extracted folder if it exists
        if os.path.exists(extracted_folder):
            shutil.rmtree(extracted_folder)

        # Save the uploaded ZIP file
        with open(zip_path, 'wb') as f:
            f.write(decoded)

        # Validate and extract the ZIP file
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Check if the ZIP file is valid
            bad_file = zip_ref.testzip()
            if bad_file:
                return None, "", f"Error: Corrupted file '{bad_file}' found in the ZIP archive."
            zip_ref.extractall(extracted_folder)

        # Identify DOSCAR and POSCAR files in the extracted folder
        doscar_path, poscar_path = None, None
        for root, dirs, files in os.walk(extracted_folder):
            for file in files:
                if file == 'DOSCAR':
                    doscar_path = os.path.join(root, file)
                elif file == 'POSCAR':
                    poscar_path = os.path.join(root, file)
            if doscar_path and poscar_path:
                break

        # Check if both DOSCAR and POSCAR files are found
        if not doscar_path or not poscar_path:
            return None, "", "Error: POSCAR or DOSCAR file not found."

        # Read atom types from POSCAR
        with open(poscar_path, 'r') as f:
            poscar_lines = f.readlines()
        atom_types = poscar_lines[5].split()
        default_colors = ['blue', 'red', 'green', 'gray', 'black', 'orange', 'purple', 'pink', 'silver']
        color_map = {atom: default_colors[i % len(default_colors)] for i, atom in enumerate(atom_types)}

        # Extract folder name for display
        folder_name = os.path.basename(os.path.dirname(doscar_path))

        return {"DOSCAR": doscar_path, "POSCAR": poscar_path}, folder_name, color_map

    except zipfile.BadZipFile:
        return None, "", "Error: Uploaded file is not a valid ZIP file."
    except Exception as e:
        return None, "", f"Error: An unexpected error occurred. {str(e)}"


@app.callback(
    Output('dos-plot', 'figure'),
    Output('xmax', 'value'),
    Output('xmin', 'value'),
    Output('action-message-store', 'data'),
    Input('uploaded-contents', 'data'),
    Input('xmin', 'value'),
    Input('xmax', 'value'),
    Input('ymin', 'value'),
    Input('ymax', 'value'),
    Input('legend-y', 'value'),
    Input({'type': 'atom-checkbox', 'index': ALL}, 'value'),
    Input({'type': 'atom-checkbox', 'index': ALL}, 'id'),
    Input({'type': 'color-dropdown', 'index': ALL}, 'value'),
    Input({'type': 'color-dropdown', 'index': ALL}, 'id'),
    Input({'type': 'toggle-total', 'index': ALL}, 'value'),
    Input({'type': 'toggle-total', 'index': ALL}, 'id'),
    Input('spin-polarization', 'data'),
    Input('show-titles', 'value'),
    Input('show-axis-scale', 'value'),
    Input('display-spins', 'value'),
    Input('legend-order', 'data'),
    State('dos-plot', 'figure')
)
def update_graph(
    contents, xmin, xmax, ymin, ymax, legend_y,
    selected_orbitals, atom_ids, selected_colors, color_ids,
    toggled_totals, toggle_ids, spin_polarized, show_titles, show_axis_scale, display_spins, legend_order, current_figure
):

    if not contents or not isinstance(contents, dict) or 'POSCAR' not in contents or 'DOSCAR' not in contents:
        return {}, None, None, "Error: POSCAR or DOSCAR file not found."

    poscar_path = contents['POSCAR']
    doscar_path = contents['DOSCAR']

    # Extract required data from the DOSCAR file
    with open(doscar_path, 'r') as f:
        lines = f.readlines()

    num_atoms, num_points, fermi_energy, lines_per_point = read_doscar_header(lines)

    # Calculate energy and atom-summed total DOS
    energy = np.array([float(line.split()[0]) - fermi_energy for line in lines[6:6 + num_points]])
    atom_dos_blocks = read_atom_dos_blocks(lines, num_atoms, num_points, fermi_energy, lines_per_point)

    with open(poscar_path, 'r') as f:
        atom_types = f.readlines()[5].split()
    num_columns = atom_dos_blocks[0].shape[1]
    total_col_indices = classify_orbitals(num_columns, atom_types)['total_col_indices']

    total_dos = np.zeros(num_points)
    for block in atom_dos_blocks:
        total_dos += np.sum(block[:, total_col_indices], axis=1)  # Sum orbital totals (skips mx/my/mz for non-collinear data)

    # Adjust the range calculation using the new atom-summed total DOS
    energy_range_mask = (energy >= (ymin if ymin is not None else -8)) & (energy <= (ymax if ymax is not None else 2))
    dos_in_range = total_dos[energy_range_mask]

    # Check if we're in spin display mode to calculate the appropriate xmax and xmin
    is_spin_display = display_spins and 'display_spins' in display_spins
    calculated_xmin = xmin  # Default to current xmin

    if is_spin_display:
        # For spin display, we need to check spin data and calculate based on individual components
        first_block = np.array([
            [float(value) for value in line.split()]
            for line in lines[6:6 + num_points]
        ])
        num_columns_first_block = len(lines[6].split())
        has_spin_data = num_columns_first_block == 5

        if has_spin_data:
            dos_up_in_range = first_block[:, 1][energy_range_mask]
            dos_down_in_range = first_block[:, 2][energy_range_mask]
            max_dos = max(np.max(dos_up_in_range) if len(dos_up_in_range) > 0 else 0,
                         np.max(dos_down_in_range) if len(dos_down_in_range) > 0 else 0)
            calculated_xmax = math.ceil(1.1 * max_dos) if max_dos > 0 else DEFAULTS["xmax"]
            calculated_xmin = -calculated_xmax  # Make symmetric for spin display
        else:
            calculated_xmax = math.ceil(1.1 * np.max(dos_in_range)) if len(dos_in_range) > 0 else DEFAULTS["xmax"]
    else:
        calculated_xmax = math.ceil(1.1 * np.max(dos_in_range)) if len(dos_in_range) > 0 else DEFAULTS["xmax"]

    # Use auto-calculated values when spin display toggles or first load
    ctx = dash.callback_context
    spin_display_changed = ctx.triggered and any('display-spins' in trigger['prop_id'] for trigger in ctx.triggered)

    # Force auto-adjustment when spin display is toggled or on initial load
    if spin_display_changed or xmax is None:
        xmax_to_use = calculated_xmax
        # Check if we have spin data for setting xmin
        if is_spin_display:
            first_block = np.array([
                [float(value) for value in line.split()]
                for line in lines[6:6 + num_points]
            ])
            num_columns_first_block = len(lines[6].split())
            has_spin_data_check = num_columns_first_block == 5
            xmin_to_use = calculated_xmin if has_spin_data_check else DEFAULTS["xmin"]
        else:
            xmin_to_use = DEFAULTS["xmin"]
    else:
        xmax_to_use = xmax
        xmin_to_use = xmin if xmin is not None else DEFAULTS["xmin"]

    # Ensure custom_colors is initialized
    custom_colors = {color_id['index']: color for color_id, color in zip(color_ids, selected_colors)} if selected_colors else {}

    # Parse the selected atoms and orbitals
    selected_atoms = {atom_id['index']: orbitals for atom_id, orbitals in zip(atom_ids, selected_orbitals) if orbitals}

    # Parse the toggled totals
    toggled_atoms = {toggle_id['index']: 'total' in toggled for toggle_id, toggled in zip(toggle_ids, toggled_totals)}

    # If no toggled totals are provided (e.g., on file load), default to showing all atomic totals
    if not toggled_totals:
        toggled_atoms = {atom_id['index']: True for atom_id in atom_ids}

    # Update the plot based on selected atoms, orbitals, toggled totals
    fig = parse_doscar_and_plot(
        doscar_path, poscar_path, xmin_to_use, xmax_to_use, ymin, ymax, legend_y, custom_colors, plot_type="total",
        spin_polarized=spin_polarized, selected_atoms=selected_atoms, toggled_atoms=toggled_atoms, show_titles=show_titles, show_axis_scale=show_axis_scale, display_spins=display_spins, legend_order=legend_order
    )

    # Return the updated plot and the calculated values
    return fig, xmax_to_use, xmin_to_use, ""


@app.callback(
    Output('save-confirmation', 'children'),
    Input('save-plot', 'n_clicks'),
    State('dos-plot', 'figure'),
    State('folder-name', 'children'),
    prevent_initial_call=True
)
def save_plot(n_clicks, figure, folder_name):
    if n_clicks:
        fig = pio.from_json(pio.to_json(figure))
        out_path = unique_download_path(get_downloads_dir(), f"{folder_name}_dos_plot.png")
        fig.write_image(str(out_path), format="png", scale=4)  # scale 4 for higher DPI (~400 DPI)
        return f"Saved to Downloads as '{out_path.name}'!"
    return ""


@app.callback(
    Output({'type': 'atom-checkbox', 'index': ALL}, 'value', allow_duplicate=True),
    Output({'type': 'toggle-total', 'index': ALL}, 'value', allow_duplicate=True),
    Input('uploaded-contents', 'data'),
    State('atom-defaults', 'data'),
    prevent_initial_call=True
)
def select_atom_totals_on_file_load(contents, atom_defaults):
    if not contents or not isinstance(contents, dict) or 'POSCAR' not in contents or 'DOSCAR' not in contents:
        raise PreventUpdate

    atom_keys = list(atom_defaults.keys())
    orbital_values = [[] for _ in atom_keys]  # No orbitals selected by default
    total_values = [['total'] for _ in atom_keys]  # All totals toggled by default

    return orbital_values, total_values


@app.callback(
    Output('atomic-contributions-container', 'children', allow_duplicate=True),
    Output('action-message-store', 'data', allow_duplicate=True),
    Output('legend-order', 'data', allow_duplicate=True),
    Input('uploaded-contents', 'data'),
    State('atom-defaults', 'data'),
    State('spin-polarization', 'data'),
    prevent_initial_call=True
)
def handle_atomic_contributions_and_debug(contents, atom_defaults, spin_polarized):
    if not contents or not isinstance(contents, dict) or 'DOSCAR' not in contents:
        return [], "Error: POSCAR or DOSCAR file not found.", []

    doscar_path = contents['DOSCAR']

    try:
        with open(doscar_path, 'r') as f:
            lines = f.readlines()

        num_atoms, num_points, fermi_energy, lines_per_point = read_doscar_header(lines)
        atom_dos_blocks = read_atom_dos_blocks(lines, num_atoms, num_points, fermi_energy, lines_per_point)

        # Determine the number of columns in the atom blocks, and map that to
        # orbital labels (handles collinear and non-collinear DOSCAR layouts)
        num_columns = atom_dos_blocks[0].shape[1]
        debug_message = f"Detected {num_columns} columns in DOSCAR."

        poscar_path = contents['POSCAR'] if isinstance(contents, dict) and 'POSCAR' in contents else None
        atom_types_for_classification = []
        if poscar_path and os.path.exists(poscar_path):
            with open(poscar_path, 'r') as f:
                atom_types_for_classification = f.readlines()[5].split()

        orbital_info = classify_orbitals(num_columns, atom_types_for_classification)
        orbital_labels = orbital_info['orbital_labels']
        if orbital_info['is_noncollinear']:
            debug_message += (
                " Non-collinear calculation detected — showing total DOS per "
                "orbital (mx/my/mz magnetization components aren't plotted yet)."
            )

        # Build a color <option> with a small swatch next to the color name
        def color_option(c):
            return {
                "label": html.Span(
                    [
                        html.Div(
                            style={
                                "backgroundColor": c,
                                "width": "13px",
                                "height": "13px",
                                "borderRadius": "3px",
                                "display": "inline-block",
                                "marginRight": "8px",
                                "border": "1px solid rgba(0,0,0,0.15)",
                            }
                        ),
                        c,
                    ],
                    style={"display": "flex", "alignItems": "center"},
                ),
                "value": c,
            }

        # Create the atom/orbital selection table
        table_header = html.Tr(
            [
                html.Th("Atom"),
                html.Th("Orbitals"),
                html.Th("Color"),
                html.Th("Total"),
                html.Th("Order"),
            ]
        )

        table_rows = []

        table_rows.append(
            html.Tr(
                [
                    html.Td("Total", className="atom-name-cell total-row"),
                    html.Td(""),
                    html.Td(
                        dcc.Dropdown(
                            id={'type': 'color-dropdown', 'index': 'Total'},
                            options=[
                                color_option(c)
                                for c in ['black', 'blue', 'red', 'green', 'gray', 'orange', 'purple', 'pink', 'silver']
                            ],
                            value='black',
                            clearable=False,
                            searchable=False,
                        ),
                        className="color-cell",
                    ),
                    html.Td(
                        dcc.Checklist(
                            id={'type': 'toggle-total', 'index': 'Total'},
                            options=[{'label': '', 'value': 'total'}],
                            value=['total'],
                            className="field-checklist",
                        )
                    ),
                    html.Td(
                        html.Div(
                            [
                                html.Button("↑", id={'type': 'order-up', 'index': 'Total'}, n_clicks=0, className="icon-btn"),
                                html.Button("↓", id={'type': 'order-down', 'index': 'Total'}, n_clicks=0, className="icon-btn"),
                            ],
                            className="order-btns",
                        )
                    ),
                ]
            )
        )

        atom_types = list(atom_defaults.keys())
        legend_order = ['Total'] + atom_types
        for atom in atom_types:
            table_rows.append(
                html.Tr(
                    [
                        html.Td(atom, className="atom-name-cell"),
                        html.Td(
                            dcc.Checklist(
                                id={'type': 'atom-checkbox', 'index': atom},
                                options=[{'label': orbital, 'value': orbital} for orbital in orbital_labels],
                                value=[],
                                className="orbital-checklist",
                            )
                        ),
                        html.Td(
                            dcc.Dropdown(
                                id={'type': 'color-dropdown', 'index': atom},
                                options=[
                                    color_option(c)
                                    for c in ['blue', 'red', 'green', 'gray', 'black', 'orange', 'purple', 'pink', 'silver']
                                ],
                                value=atom_defaults.get(atom, 'blue'),
                                clearable=False,
                                searchable=False,
                            ),
                            className="color-cell",
                        ),
                        html.Td(
                            dcc.Checklist(
                                id={'type': 'toggle-total', 'index': atom},
                                options=[{'label': '', 'value': 'total'}],
                                value=['total'],
                                className="field-checklist",
                            )
                        ),
                        html.Td(
                            html.Div(
                                [
                                    html.Button("↑", id={'type': 'order-up', 'index': atom}, n_clicks=0, className="icon-btn"),
                                    html.Button("↓", id={'type': 'order-down', 'index': atom}, n_clicks=0, className="icon-btn"),
                                ],
                                className="order-btns",
                            )
                        ),
                    ]
                )
            )

        table = html.Div(
            html.Table([table_header] + table_rows, className="data-table"),
            className="table-scroll",
        )

        return table, debug_message, legend_order
    except Exception as e:
        return [], f"Error processing DOSCAR file: {str(e)}", []


@app.callback(
    Output('debug-message', 'children'),
    Input('action-message-store', 'data')
)
def display_debug_message(debug_message):
    return debug_message


@app.callback(
    [Output('xmin', 'value', allow_duplicate=True),
     Output('xmax', 'value', allow_duplicate=True),
     Output('ymin', 'value', allow_duplicate=True),
     Output('ymax', 'value', allow_duplicate=True)],
    [Input('reset-axes', 'n_clicks')],
    [State('xmin', 'value'),
     State('xmax', 'value'),
     State('ymin', 'value'),
     State('ymax', 'value'),
     State('uploaded-contents', 'data')],
    prevent_initial_call=True
)
def handle_axes_and_update(reset_clicks, xmin, xmax, ymin, ymax, contents):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise PreventUpdate

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    if trigger_id == 'reset-axes':
        if not contents or not isinstance(contents, dict) or 'DOSCAR' not in contents:
            return DEFAULTS["xmin"], DEFAULTS["xmax"], DEFAULTS["ymin"], DEFAULTS["ymax"]

        doscar_path = contents['DOSCAR']
        poscar_path = contents.get('POSCAR')

        # Calculate the buffer value for xmax based on the DOSCAR file
        try:
            with open(doscar_path, 'r') as f:
                lines = f.readlines()

            num_atoms, num_points, fermi_energy, lines_per_point = read_doscar_header(lines)
            energy = np.array([float(line.split()[0]) - fermi_energy for line in lines[6:6 + num_points]])
            total_dos = np.zeros(num_points)

            atom_dos_blocks = read_atom_dos_blocks(lines, num_atoms, num_points, fermi_energy, lines_per_point)
            atom_types = []
            if poscar_path and os.path.exists(poscar_path):
                with open(poscar_path, 'r') as f:
                    atom_types = f.readlines()[5].split()
            num_columns = atom_dos_blocks[0].shape[1]
            total_col_indices = classify_orbitals(num_columns, atom_types)['total_col_indices']
            for block in atom_dos_blocks:
                total_dos += np.sum(block[:, total_col_indices], axis=1)

            energy_range_mask = (energy >= DEFAULTS["ymin"]) & (energy <= DEFAULTS["ymax"])
            dos_in_range = total_dos[energy_range_mask]
            calculated_xmax = math.ceil(1.1 * np.max(dos_in_range)) if len(dos_in_range) > 0 else DEFAULTS["xmax"]

            return DEFAULTS["xmin"], calculated_xmax, DEFAULTS["ymin"], DEFAULTS["ymax"]

        except Exception:
            # Fallback to defaults if an error occurs
            return DEFAULTS["xmin"], DEFAULTS["xmax"], DEFAULTS["ymin"], DEFAULTS["ymax"]

    raise PreventUpdate


@app.callback(
    Output('spin-message', 'children'),
    Input('uploaded-contents', 'data')
)
def update_spin_message(contents):
    if not contents or not isinstance(contents, dict) or 'DOSCAR' not in contents:
        return "Upload a file to see spin-polarization and orbital detection details here."

    doscar_path = contents['DOSCAR']

    try:
        with open(doscar_path, 'r') as f:
            lines = f.readlines()

        # Check the first block for spin-polarization
        num_columns_first_block = len(lines[6].split())
        if num_columns_first_block == 5:
            spin_message = "Spin-polarized collinear calculation detected (ISPIN=2). This means the calculation includes spin-up and spin-down states."
        elif num_columns_first_block == 3:
            spin_message = "Non-spin-polarized calculation detected (ISPIN=1, or not entered as it is the default). This means the calculation does not include spin-up and spin-down states."
        else:
            spin_message = "Unknown DOSCAR format detected. Unable to determine spin polarization."

        # Check the second block for lm-resolved / non-collinear orbital layouts
        num_atoms, num_points, fermi_energy, lines_per_point = read_doscar_header(lines)
        atom_dos_blocks = read_atom_dos_blocks(lines, num_atoms, num_points, fermi_energy, lines_per_point)
        num_columns = atom_dos_blocks[0].shape[1]

        poscar_path = contents['POSCAR'] if isinstance(contents, dict) and 'POSCAR' in contents else None
        atom_types = []
        if poscar_path and os.path.exists(poscar_path):
            with open(poscar_path, 'r') as f:
                atom_types = f.readlines()[5].split()

        orbital_info = classify_orbitals(num_columns, atom_types)
        if orbital_info['is_noncollinear']:
            # The total block alone can't distinguish non-collinear from
            # ISPIN=1 (both have 3 columns: energy, DOS, integrated DOS) --
            # VASP does force ISPIN=1 internally for non-collinear runs, so
            # that message isn't wrong, just incomplete. Override it here
            # since the atom block unambiguously shows non-collinear data.
            spin_message = "Non-collinear calculation detected (LNONCOLLINEAR=.TRUE., internally ISPIN=1)."
        orbital_message = orbital_info['description']

        spin_message += f" {orbital_message}"
        return spin_message

    except Exception as e:
        return f"Error processing DOSCAR file: {str(e)}"


@app.callback(
    Output('upload-data', 'contents', allow_duplicate=True),
    Input('demo-file', 'n_clicks'),
    prevent_initial_call=True
)
def load_demo_file(n_clicks):
    if n_clicks:
        demo_path = resource_path("resources", "ISPIN2_LORBIT14.zip")
        if not os.path.exists(demo_path):
            return dash.no_update
        with open(demo_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
        mime_type = mimetypes.guess_type(demo_path)[0] or "application/zip"
        contents = f"data:{mime_type};base64,{encoded}"
        return contents
    return dash.no_update


@app.callback(
    Output('legend-order', 'data', allow_duplicate=True),
    [Input({'type': 'order-up', 'index': ALL}, 'n_clicks'),
     Input({'type': 'order-down', 'index': ALL}, 'n_clicks')],
    [State('legend-order', 'data')],
    prevent_initial_call=True
)
def update_legend_order(up_clicks, down_clicks, legend_order):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise PreventUpdate

    # Make a copy of the legend order to avoid mutating the original
    new_legend_order = legend_order.copy() if legend_order else []

    trigger = ctx.triggered[0]['prop_id']
    # Extract the atom name or 'Total' from the trigger string
    match = re.search(r'index":\s*"([^"]+)"', trigger)
    if not match:
        return new_legend_order

    name = match.group(1)
    if not new_legend_order or name not in new_legend_order:
        return new_legend_order

    idx = new_legend_order.index(name)

    if 'order-up' in trigger and idx > 0:
        # Move item up (swap with previous item)
        new_legend_order[idx-1], new_legend_order[idx] = new_legend_order[idx], new_legend_order[idx-1]
    elif 'order-down' in trigger and idx < len(new_legend_order)-1:
        # Move item down (swap with next item)
        new_legend_order[idx+1], new_legend_order[idx] = new_legend_order[idx], new_legend_order[idx+1]

    return new_legend_order


# ==========================================================================
# Mode switcher (DOSCAR Plotter <-> COHP/COOP Plotter)
# ==========================================================================

MODE_SUBTITLES = {
    "doscar": "Density of states visualizer",
    "cohp": "COHP / COOP bonding visualizer",
}


@app.callback(
    Output('doscar-page', 'style'),
    Output('cohp-page', 'style'),
    Output('mode-subtitle', 'children'),
    Input('app-mode', 'value'),
)
def switch_mode(mode):
    if mode == 'cohp':
        return {'display': 'none'}, {'display': 'flex'}, MODE_SUBTITLES['cohp']
    return {'display': 'flex'}, {'display': 'none'}, MODE_SUBTITLES['doscar']


@app.callback(
    Output('folder-badge-display', 'children'),
    Input('app-mode', 'value'),
    Input('folder-name', 'children'),
    Input('cc-folder-name', 'children'),
)
def update_folder_badge(mode, doscar_folder, cohp_folder):
    if mode == 'cohp':
        return cohp_folder or ''
    return doscar_folder or ''


# ==========================================================================
# COHP / COOP Plotter — ported from cohp-coop-gui/app.py. Component ids are
# prefixed with "cc-" to keep this page's callback graph independent of the
# DOSCAR Plotter page sharing the window; the parsing/plotting logic lives in
# src/cohp_coop.py and is otherwise unchanged from the original app.
# ==========================================================================

@app.callback(
    Output('cc-upload-data', 'contents', allow_duplicate=True),
    Input('cc-demo-file', 'n_clicks'),
    prevent_initial_call=True
)
def cc_load_demo_file(n_clicks):
    if n_clicks:
        demo_path = resource_path("resources", "CeCoAl4.zip")
        if not os.path.exists(demo_path):
            return dash.no_update
        with open(demo_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
        mime_type = mimetypes.guess_type(demo_path)[0] or "application/zip"
        return f"data:{mime_type};base64,{encoded}"
    return dash.no_update


@app.callback(
    Output('cc-uploaded-contents', 'data'),
    Output('cc-folder-name', 'children'),
    Input('cc-upload-data', 'contents'),
    State('cc-upload-data', 'filename'),
    prevent_initial_call=True
)
def cc_handle_upload(contents, filename):
    if not contents:
        raise PreventUpdate
    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    with zipfile.ZipFile(BytesIO(decoded), 'r') as zip_ref:
        files = zip_ref.namelist()
        cohp_file = next((f for f in files if "COHPCAR" in f), None)
        coop_file = next((f for f in files if "COOPCAR" in f), None)
        cohp_data = zip_ref.read(cohp_file).decode('utf-8') if cohp_file else None
        coop_data = zip_ref.read(coop_file).decode('utf-8') if coop_file else None

        if not filename or filename == "COHP":
            folder_name = os.path.splitext(os.path.basename("CeCoAl4.zip"))[0]
        else:
            folder_name = os.path.splitext(os.path.basename(filename))[0]

        unique_pairs = extract_unique_pairs(cohp_data, coop_data)
        return {
            "cohp_data": cohp_data,
            "coop_data": coop_data,
            "unique_pairs": unique_pairs,
            "folder_name": folder_name,
        }, folder_name


@app.callback(
    Output('cc-element-pair-table', 'children'),
    Input('cc-uploaded-contents', 'data'),
    prevent_initial_call=True
)
def cc_build_element_pair_table(data):
    if not data or "unique_pairs" not in data:
        return ""

    def color_option(c):
        return {
            "label": html.Span(
                [
                    html.Div(
                        style={
                            "backgroundColor": c,
                            "width": "13px",
                            "height": "13px",
                            "borderRadius": "3px",
                            "display": "inline-block",
                            "marginRight": "8px",
                            "border": "1px solid rgba(0,0,0,0.15)",
                        }
                    ),
                    c,
                ],
                style={"display": "flex", "alignItems": "center"},
            ),
            "value": c,
        }

    color_options = [
        color_option(c)
        for c in ['blue', 'red', 'green', 'gray', 'black', 'orange', 'purple', 'pink', 'silver']
    ]
    table_header = html.Tr([
        html.Th("Pair"),
        html.Th("Color"),
        html.Th("Show"),
        html.Th("ICOHP/ICOOP"),
    ])
    table_rows = []
    color_cycle = ['red', 'green', 'blue', 'orange']
    for i, pair in enumerate(data["unique_pairs"]):
        pair_str = f"{pair[0]}-{pair[1]}"
        default_color = color_cycle[i % len(color_cycle)]
        table_rows.append(html.Tr([
            html.Td(pair_str, className="atom-name-cell"),
            html.Td(
                dcc.Dropdown(
                    id={'type': 'cc-color-dropdown', 'index': pair_str},
                    options=color_options,
                    value=default_color,
                    clearable=False,
                    searchable=False,
                ),
                className="color-cell",
            ),
            html.Td(
                dcc.Checklist(
                    id={'type': 'cc-toggle-pair', 'index': pair_str},
                    options=[{'label': '', 'value': 'show'}],
                    value=['show'],
                    className="field-checklist",
                )
            ),
            html.Td(
                dcc.Checklist(
                    id={'type': 'cc-toggle-icohp', 'index': pair_str},
                    options=[{'label': '', 'value': 'icohp'}],
                    value=[],
                    className="field-checklist",
                )
            ),
        ]))
    return html.Div(
        html.Table([table_header] + table_rows, className="data-table"),
        className="table-scroll",
    )


@app.callback(
    Output('cc-cohp-plot', 'figure'),
    Input('cc-uploaded-contents', 'data'),
    Input({'type': 'cc-color-dropdown', 'index': ALL}, 'value'),
    Input({'type': 'cc-toggle-pair', 'index': ALL}, 'value'),
    Input({'type': 'cc-toggle-icohp', 'index': ALL}, 'value'),
    Input('cc-xmin-cohp', 'value'), Input('cc-xmax-cohp', 'value'),
    Input('cc-ymin-cohp', 'value'), Input('cc-ymax-cohp', 'value'),
    Input('cc-legend-y-cohp', 'value'),
    Input('cc-legend-x-cohp', 'value'),
    Input('cc-show-titles-cohp', 'value'),
    Input('cc-show-axis-scale-cohp', 'value'),
    prevent_initial_call=True
)
def cc_update_cohp_plot(data, colors, toggles, icohp_toggles, xmin, xmax, ymin, ymax,
                         legend_y, legend_x, show_titles, show_axis_scale):
    if not data or not data.get("cohp_data"):
        return go.Figure()
    pairs = [f"{p[0]}-{p[1]}" for p in data["unique_pairs"]]
    color_map = {pair: colors[i] if i < len(colors) else 'blue' for i, pair in enumerate(pairs)}
    show_map = {pair: ('show' in toggles[i] if i < len(toggles) else True) for i, pair in enumerate(pairs)}
    icohp_map = {pair: ('icohp' in icohp_toggles[i] if i < len(icohp_toggles) else False) for i, pair in enumerate(pairs)}
    return build_bonding_figure(
        data["cohp_data"], data.get("folder_name", ""), data["unique_pairs"],
        color_map, show_map, icohp_map,
        xmin, xmax, ymin, ymax, legend_x, legend_y, show_titles, show_axis_scale,
        kind="COHP",
    )


@app.callback(
    Output('cc-coop-plot', 'figure'),
    Input('cc-uploaded-contents', 'data'),
    Input({'type': 'cc-color-dropdown', 'index': ALL}, 'value'),
    Input({'type': 'cc-toggle-pair', 'index': ALL}, 'value'),
    Input({'type': 'cc-toggle-icohp', 'index': ALL}, 'value'),
    Input('cc-xmin-coop', 'value'), Input('cc-xmax-coop', 'value'),
    Input('cc-ymin-coop', 'value'), Input('cc-ymax-coop', 'value'),
    Input('cc-legend-y-coop', 'value'),
    Input('cc-legend-x-coop', 'value'),
    Input('cc-show-titles-coop', 'value'),
    Input('cc-show-axis-scale-coop', 'value'),
    prevent_initial_call=True
)
def cc_update_coop_plot(data, colors, toggles, icohp_toggles, xmin, xmax, ymin, ymax,
                         legend_y, legend_x, show_titles, show_axis_scale):
    if not data or not data.get("coop_data"):
        return go.Figure()
    pairs = [f"{p[0]}-{p[1]}" for p in data["unique_pairs"]]
    color_map = {pair: colors[i] if i < len(colors) else 'blue' for i, pair in enumerate(pairs)}
    show_map = {pair: ('show' in toggles[i] if i < len(toggles) else True) for i, pair in enumerate(pairs)}
    icohp_map = {pair: ('icohp' in icohp_toggles[i] if i < len(icohp_toggles) else False) for i, pair in enumerate(pairs)}
    return build_bonding_figure(
        data["coop_data"], data.get("folder_name", ""), data["unique_pairs"],
        color_map, show_map, icohp_map,
        xmin, xmax, ymin, ymax, legend_x, legend_y, show_titles, show_axis_scale,
        kind="COOP",
    )


@app.callback(
    Output('cc-save-confirmation', 'children'),
    Input('cc-save-plot', 'n_clicks'),
    State('cc-cohp-plot', 'figure'),
    State('cc-folder-name', 'children'),
    prevent_initial_call=True
)
def cc_save_cohp_plot(n_clicks, figure, folder_name):
    if n_clicks:
        fig = pio.from_json(pio.to_json(figure))
        fig.update_layout(plot_bgcolor='white', paper_bgcolor='white')
        out_path = unique_download_path(get_downloads_dir(), f"{folder_name}_COHP_plot.png")
        fig.write_image(str(out_path), format="png", scale=4)
        return f"Saved to Downloads as '{out_path.name}'!"
    return ""


@app.callback(
    Output('cc-save-coop-confirmation', 'children'),
    Input('cc-save-coop-plot', 'n_clicks'),
    State('cc-coop-plot', 'figure'),
    State('cc-folder-name', 'children'),
    prevent_initial_call=True
)
def cc_save_coop_plot(n_clicks, figure, folder_name):
    if n_clicks:
        fig = pio.from_json(pio.to_json(figure))
        fig.update_layout(plot_bgcolor='white', paper_bgcolor='white')
        out_path = unique_download_path(get_downloads_dir(), f"{folder_name}_COOP_plot.png")
        fig.write_image(str(out_path), format="png", scale=4)
        return f"Saved to Downloads as '{out_path.name}'!"
    return ""


@app.callback(
    Output('cc-xmin-cohp', 'value', allow_duplicate=True),
    Output('cc-xmax-cohp', 'value', allow_duplicate=True),
    Output('cc-ymin-cohp', 'value', allow_duplicate=True),
    Output('cc-ymax-cohp', 'value', allow_duplicate=True),
    Output('cc-xmin-coop', 'value', allow_duplicate=True),
    Output('cc-xmax-coop', 'value', allow_duplicate=True),
    Output('cc-ymin-coop', 'value', allow_duplicate=True),
    Output('cc-ymax-coop', 'value', allow_duplicate=True),
    Input('cc-reset-axes', 'n_clicks'),
    prevent_initial_call=True
)
def cc_reset_axes(n_clicks):
    if n_clicks:
        return (
            COHP_DEFAULTS["xmin"], COHP_DEFAULTS["xmax"], COHP_DEFAULTS["ymin"], COHP_DEFAULTS["ymax"],
            COHP_DEFAULTS["xmin"], COHP_DEFAULTS["xmax"], COHP_DEFAULTS["ymin"], COHP_DEFAULTS["ymax"],
        )
    raise PreventUpdate


@app.callback(
    Output('cc-cohp-warning', 'children'),
    Input('cc-uploaded-contents', 'data')
)
def cc_cohp_warning(data):
    if not data or not data.get("cohp_data"):
        return "No COHPCAR.lobster found in ZIP."
    return ""


@app.callback(
    Output('cc-coop-warning', 'children'),
    Input('cc-uploaded-contents', 'data')
)
def cc_coop_warning(data):
    if not data or not data.get("coop_data"):
        return "No COOPCAR.lobster found in ZIP."
    return ""


@app.callback(
    Output('cc-xmin-cohp', 'value'),
    Output('cc-xmax-cohp', 'value'),
    Output('cc-xmin-coop', 'value'),
    Output('cc-xmax-coop', 'value'),
    Input('cc-uploaded-contents', 'data'),
    prevent_initial_call=True
)
def cc_set_auto_x_limits_on_upload(data):
    if not data:
        raise PreventUpdate
    auto_xmin_cohp, auto_xmax_cohp = auto_x_limits(data.get("cohp_data"), data["unique_pairs"], "COHP")
    auto_xmin_coop, auto_xmax_coop = auto_x_limits(data.get("coop_data"), data["unique_pairs"], "COOP")
    return auto_xmin_cohp, auto_xmax_cohp, auto_xmin_coop, auto_xmax_coop


if __name__ == '__main__':
    port = int(os.environ.get('DOSCAR_PORT', 8050))
    app.run(debug=False, host='127.0.0.1', port=port)
