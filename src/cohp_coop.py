"""
COHP/COOP parsing and Plotly figure construction — ported from cohp-coop-gui's
app.py (originally inline in its Dash callbacks) with the COHP and COOP code
paths consolidated into shared helpers, since they were near-identical aside
from a sign flip and a couple of labels. No numeric behavior was changed.
"""

import re
from io import StringIO

import numpy as np
import plotly.graph_objects as go

PAIR_RE = re.compile(r":([A-Za-z]+)\d+->([A-Za-z]+)\d+\(")

DEFAULTS = {
    "xmin": -30,
    "xmax": 30,
    "ymin": -8,
    "ymax": 2,
    "legend_y": 0.26,
    "legend_x": 0.95,
}

# Fixed energy window the original app always used for auto-scaling the
# x-axis, independent of whatever ymin/ymax the user has dialed in.
AUTO_RANGE_YMIN, AUTO_RANGE_YMAX = -8, 2


def subscript_numbers(text):
    sub_map = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
    return re.sub(r'(\d+)', lambda m: m.group(0).translate(sub_map), text)


def _pair_from_line(line):
    match = PAIR_RE.search(line)
    if not match:
        return None
    atom1, atom2 = match.groups()
    return (atom1, atom2) if atom1 == atom2 else tuple(sorted([atom1, atom2]))


def extract_unique_pairs(cohp_data, coop_data):
    """Unique, sorted (atom1, atom2) pairs found in either file's interaction list."""
    unique_pairs = set()
    for file_data in (cohp_data, coop_data):
        if file_data:
            for line in file_data.splitlines():
                if line.startswith("No."):
                    pair = _pair_from_line(line)
                    if pair:
                        unique_pairs.add(pair)
    return sorted(unique_pairs)


def parse_bonding_block(raw_text):
    """Parse a COHPCAR.lobster / COOPCAR.lobster text blob.

    Returns (energy, data_arr, interaction_to_pair):
      - energy: 1D array, column 0 of the data block.
      - data_arr: full numeric block (energy, avg, avg-integrated, then each
        interaction's [value, integrated-value] pair of columns).
      - interaction_to_pair: for each interaction column-pair (in file order),
        the (atom1, atom2) tuple it belongs to.
    """
    lines = raw_text.splitlines()
    header_idx = next(i for i, line in enumerate(lines) if line.strip().startswith("No.1"))
    data_start_idx = header_idx + 1
    numeric_lines = []
    for line in lines[data_start_idx:]:
        tokens = line.strip().split()
        if tokens and re.match(r'^-?\d+\.?\d*([eE][-+]?\d+)?$', tokens[0]):
            numeric_lines.append(line)
    data_arr = np.genfromtxt(StringIO("\n".join(numeric_lines)))
    energy = data_arr[:, 0]

    interaction_to_pair = []
    for line in lines:
        if line.startswith("No."):
            pair = _pair_from_line(line)
            if pair:
                interaction_to_pair.append(pair)

    return energy, data_arr, interaction_to_pair


def get_dynamic_xrange(energy, y_min, y_max, traces):
    """Auto x-axis half-width from the max |value| of `traces` within [y_min, y_max]."""
    mask = (energy >= y_min) & (energy <= y_max)
    max_abs = 0
    for arr in traces:
        if arr is not None and arr.shape == energy.shape:
            arr_in_window = arr[mask]
            if arr_in_window.size > 0:
                max_abs = max(max_abs, np.max(np.abs(arr_in_window)))
    if max_abs == 0:
        max_abs = 1  # fallback to avoid zero width
    buffer = max_abs * 0.05
    return -max_abs - buffer, max_abs + buffer


def compute_pair_sums(energy, data_arr, interaction_to_pair, unique_pairs, sign):
    """Per-pair summed value and integrated-value traces.

    sign=-1 for COHP (the file stores -COHP as the "bonding-positive"
    convention, undone here to get plain COHP magnitudes), sign=+1 for COOP.
    Returns (sums, integrated), each a dict keyed by "Atom1-Atom2" string.
    """
    sums = {}
    integrated = {}
    for pair in unique_pairs:
        pair_str = f"{pair[0]}-{pair[1]}"
        indices = [j for j, p in enumerate(interaction_to_pair) if p == tuple(pair)]
        pair_sum = np.zeros_like(energy)
        pair_integrated = np.zeros_like(energy)
        for idx in indices:
            col = 3 + 2 * idx
            icol = 4 + 2 * idx
            pair_sum += sign * data_arr[:, col]
            pair_integrated += sign * data_arr[:, icol]
        sums[pair_str] = pair_sum
        integrated[pair_str] = pair_integrated
    return sums, integrated


def auto_x_limits(raw_data, unique_pairs, kind):
    """Auto xmin/xmax (rounded to int) from ALL pairs, used right after upload
    to seed the numeric axis-limit inputs — mirrors the original app's
    upload-time behavior, which (unlike the live plot recompute) does not
    exclude pairs the user has hidden, since nothing has been toggled yet."""
    if not raw_data:
        return None, None
    sign = -1 if kind == "COHP" else 1
    energy, data_arr, interaction_to_pair = parse_bonding_block(raw_data)
    sums, _ = compute_pair_sums(energy, data_arr, interaction_to_pair, unique_pairs, sign)
    xmin, xmax = get_dynamic_xrange(energy, AUTO_RANGE_YMIN, AUTO_RANGE_YMAX, list(sums.values()))
    return int(round(xmin)), int(round(xmax))


def build_bonding_figure(
    raw_data, folder_name, unique_pairs, color_map, show_map, icohp_map,
    xmin, xmax, ymin, ymax, legend_x, legend_y, show_titles, show_axis_scale,
    kind,
):
    """Build the COHP or COOP figure. `kind` is 'COHP' or 'COOP'."""
    sign = -1 if kind == "COHP" else 1
    integrated_label = "ICOHP" if kind == "COHP" else "ICOOP"
    x_axis_title_text = "-COHP" if kind == "COHP" else "COOP"

    energy, data_arr, interaction_to_pair = parse_bonding_block(raw_data)
    pair_sums, pair_integrated = compute_pair_sums(
        energy, data_arr, interaction_to_pair, unique_pairs, sign
    )

    visible_traces = [
        pair_sums[f"{p[0]}-{p[1]}"]
        for p in unique_pairs
        if show_map.get(f"{p[0]}-{p[1]}", True)
    ]
    auto_xmin, auto_xmax = get_dynamic_xrange(
        energy, AUTO_RANGE_YMIN, AUTO_RANGE_YMAX, visible_traces
    )

    xmax_val = xmax if xmax is not None else auto_xmax
    xmin_val = xmin if xmin is not None else auto_xmin
    ymax_val = ymax if ymax is not None else AUTO_RANGE_YMAX
    ymin_val = ymin if ymin is not None else AUTO_RANGE_YMIN

    fig = go.Figure()
    for pair in unique_pairs:
        pair_str = f"{pair[0]}-{pair[1]}"
        if not show_map.get(pair_str, True):
            continue
        fig.add_trace(go.Scatter(
            x=pair_sums[pair_str], y=energy,
            mode="lines",
            name=pair_str,
            line=dict(width=2.25, color=color_map.get(pair_str, "blue")),
        ))
        if icohp_map.get(pair_str, False):
            fig.add_trace(go.Scatter(
                x=pair_integrated[pair_str], y=energy,
                mode="lines",
                name=integrated_label,
                line=dict(width=2.25, color=color_map.get(pair_str, "blue"), dash="dash"),
                showlegend=True,
            ))

    fig.add_hline(y=0, line_dash="dash", line_color="black", line_width=2)
    fig.add_vline(x=0, line_dash="dash", line_color="black", line_width=2)

    if legend_y is None:
        legend_y = DEFAULTS["legend_y"]
    if legend_x is None:
        legend_x = DEFAULTS["legend_x"]

    folder_name_unicode = subscript_numbers(folder_name or "")
    plot_title = f"{folder_name_unicode} {kind}" if show_titles and "plot_title" in show_titles else None
    x_title = x_axis_title_text if show_titles and "x_title" in show_titles else ""
    y_title = "Energy (eV)" if show_titles and "y_title" in show_titles else ""
    show_x_scale = bool(show_axis_scale) and "x_scale" in show_axis_scale
    show_y_scale = bool(show_axis_scale) and "y_scale" in show_axis_scale

    fig.update_layout(
        font=dict(family="DejaVu Sans, Arial, sans-serif", size=20, color="black"),
        title=dict(
            text=plot_title,
            x=0.5,
            xanchor="center",
            y=0.98,
            font=dict(size=20, family="DejaVu Sans, Arial, sans-serif"),
        ) if plot_title else None,
        xaxis=dict(
            title=dict(
                text=x_title,
                font=dict(size=20, family="DejaVu Sans, Arial, sans-serif"),
            ),
            range=[xmin_val, xmax_val],
            showgrid=False,
            zeroline=True,
            zerolinewidth=3,
            zerolinecolor="black",
            tickfont=dict(size=20, family="DejaVu Sans, Arial, sans-serif"),
            tickwidth=2,
            ticklen=8,
            tickcolor="black",
            ticks="outside" if show_x_scale else "",
            automargin=True,
            showticklabels=show_x_scale,
        ),
        yaxis=dict(
            title=dict(
                text=y_title,
                font=dict(size=20, family="DejaVu Sans, Arial, sans-serif"),
            ),
            range=[ymin_val, ymax_val],
            showgrid=False,
            zeroline=False,
            tickfont=dict(size=20, family="DejaVu Sans, Arial, sans-serif"),
            tickwidth=2,
            ticklen=8,
            tickcolor="black",
            ticks="outside" if show_y_scale else "",
            showticklabels=show_y_scale,
        ),
        legend=dict(
            x=legend_x, y=legend_y, xanchor="right", yanchor="top",
            bgcolor="rgba(0,0,0,0)",
            tracegroupgap=0,
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=50, r=50, t=50, b=50),
        height=725,
        width=400,
    )

    fig.add_annotation(
        x=xmax_val,
        y=0,
        text="<i>E</i><sub><i>F</i></sub>",
        showarrow=False,
        font=dict(size=20, family="DejaVu Sans, Arial, sans-serif", color="black"),
        xanchor="left",
        yanchor="middle",
        xshift=2,
        yshift=0,
        align="left",
    )

    fig.add_shape(
        type="rect",
        x0=0, y0=0, x1=1, y1=1,
        xref="paper", yref="paper",
        line=dict(color="black", width=2),
        fillcolor="rgba(0,0,0,0)",
    )

    return fig
