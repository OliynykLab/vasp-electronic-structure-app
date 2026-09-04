import os
import re
import numpy as np
import plotly.graph_objs as go

# Define Mendeleev numbers
mendeleev_numbers = {
    "H": 92, "He": 98, "Li": 1, "Be": 67, "B": 72, "C": 77, "N": 82, "O": 87, "F": 93, "Ne": 99,
    "Na": 2, "Mg": 68, "Al": 73, "Si": 78, "P": 83, "S": 88, "Cl": 94, "Ar": 100, "K": 3, "Ca": 7,
    "Sc": 11, "Ti": 43, "V": 46, "Cr": 49, "Mn": 52, "Fe": 55, "Co": 58, "Ni": 61, "Cu": 64, "Zn": 69,
    "Ga": 74, "Ge": 79, "As": 84, "Se": 89, "Br": 95, "Kr": 101, "Rb": 4, "Sr": 8, "Y": 12, "Zr": 44,
    "Nb": 47, "Mo": 50, "Tc": 53, "Ru": 56, "Rh": 59, "Pd": 62, "Ag": 65, "Cd": 70, "In": 75,
    "Sn": 80, "Sb": 85, "Te": 90, "I": 96, "Xe": 102, "Cs": 5, "Ba": 9, "La": 13, "Ce": 15,
    "Pr": 17, "Nd": 19, "Pm": 21, "Sm": 23, "Eu": 25, "Gd": 27, "Tb": 29, "Dy": 31, "Ho": 33,
    "Er": 35, "Tm": 37, "Yb": 39, "Lu": 41, "Hf": 45, "Ta": 48, "W": 51, "Re": 54, "Os": 57,
    "Ir": 60, "Pt": 63, "Au": 66, "Hg": 71, "Tl": 76, "Pb": 81, "Bi": 86, "Po": 91, "At": 97,
    "Rn": 103, "Fr": 6, "Ra": 10, "Ac": 14, "Th": 16, "Pa": 18, "U": 20, "Np": 22, "Pu": 24,
    "Am": 26, "Cm": 28, "Bk": 30, "Cf": 32, "Es": 34, "Fm": 36, "Md": 38, "No": 40, "Lr": 42,
}

# f-block elements, used to disambiguate the ambiguous "5 columns" (s, p, d, f
# grouped) case from "5 columns" (s, py, pz, px lm-resolved, no d) case.
f_elements = [
    "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu",
    "Th", "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr"
]

# Non-collinear calculations (LNONCOLLINEAR = .TRUE.) print, for every orbital
# (or orbital group), 4 columns instead of 1 (non-spin) or 2 (ISPIN=2): the
# total DOS plus the mx/my/mz magnetization density. So the per-atom block's
# value-column count is (number of orbital groups) * 4 instead of * 1 or * 2.
# Column count alone can't always disambiguate this from a collinear file (a
# non-collinear "4 groups" block and a collinear "16 columns, no spin" block
# both have 16 value columns) -- see GitHub issue #4 -- but the common
# LORBIT=11/12 cases below are unambiguous, since no collinear layout produces
# 12, 36 or 64 value columns.
NONCOLLINEAR_ORBITAL_GROUPS = {
    12: ['s', 'p', 'd'],
    36: ['s', 'py', 'pz', 'px', 'dxy', 'dyz', 'dz²', 'dxz', 'dx²-y²'],
    64: ['s', 'py', 'pz', 'px', 'dxy', 'dyz', 'dz²', 'dxz', 'dx²-y²',
         'fx(3x²-y²)', 'fxyz', 'fyz²', 'fz³', 'fxz²', 'fx(x²-y²)', 'fx(x²-3y²)'],
}


def read_doscar_header(lines):
    """Parse the leading DOSCAR header fields.

    Returns (num_atoms, num_points, fermi_energy, lines_per_point).

    ``lines_per_point`` is normally 1 (one physical line per energy point per
    atom), but VASP wraps very wide rows -- e.g. non-collinear + lm-resolved +
    f-orbitals, which need 1 + 16*4 = 65 values -- across multiple physical
    lines by reapplying the same FORTRAN format. That wrap width isn't
    documented, so it's inferred here from the file's own line count instead
    of being hard-coded.
    """
    num_atoms = int(lines[0].split()[0])
    num_points = int(lines[5].split()[2])
    fermi_energy = float(lines[5].split()[3])

    denom = num_atoms * num_points
    remaining_lines = len(lines) - 6 - num_points - num_atoms
    if denom > 0 and remaining_lines > 0 and remaining_lines % denom == 0:
        lines_per_point = remaining_lines // denom
    else:
        lines_per_point = 1

    return num_atoms, num_points, fermi_energy, lines_per_point


def read_atom_dos_blocks(lines, num_atoms, num_points, fermi_energy, lines_per_point):
    """Read the per-atom projected-DOS blocks that follow the total DOS block.

    Each returned block is an array of shape (num_points, 1 + value_columns);
    column 0 is energy (relative to the Fermi level).
    """
    atom_dos_blocks = []
    current_line = 6 + num_points
    for _ in range(num_atoms):
        current_line += 1  # skip this atom's own header line
        block_rows = []
        for i in range(num_points):
            row_start = current_line + i * lines_per_point
            tokens = []
            for k in range(lines_per_point):
                tokens.extend(lines[row_start + k].split())
            block_rows.append([float(tokens[0]) - fermi_energy] + [float(v) for v in tokens[1:]])
        atom_dos_blocks.append(np.array(block_rows))
        current_line += num_points * lines_per_point
    return atom_dos_blocks


def classify_orbitals(num_columns, atom_types):
    """Map a per-atom DOSCAR block's column count to orbital labels.

    ``num_columns`` includes the leading energy column. ``atom_types`` is the
    list of element symbols from the POSCAR, used only to disambiguate the
    "5 columns" collinear case (s/p/d/f grouped vs. s/py/pz/px lm-resolved).

    Returns a dict with:
      - orbital_labels: list of orbital names for the per-atom checkboxes/plot
      - orbital_indices: {label: column index} -- for non-collinear data this
        points at each orbital's *total* (charge) sub-column, skipping its
        mx/my/mz magnetization sub-columns
      - total_col_indices: the columns to sum for an atom's "all orbitals"
        total contribution (all value columns for collinear data; just the
        total sub-columns for non-collinear data)
      - is_noncollinear, is_spin_polarized, is_spin_polarized_and_im_resolved,
        f_orbitals_spin, f_orbitals_im_resolved_spin: booleans used by the
        plotting code to decide how to build traces
      - description: a short human-readable string describing what was
        detected, suitable for a status/debug message
    """
    value_cols = num_columns - 1
    contains_f_element = any(elem in atom_types for elem in f_elements)

    noncollinear_labels = NONCOLLINEAR_ORBITAL_GROUPS.get(value_cols)
    if noncollinear_labels is not None:
        group_size = len(noncollinear_labels)
        total_col_indices = [1 + 4 * i for i in range(group_size)]
        return {
            'orbital_labels': noncollinear_labels,
            'orbital_indices': dict(zip(noncollinear_labels, total_col_indices)),
            'total_col_indices': total_col_indices,
            'is_noncollinear': True,
            'is_spin_polarized': False,
            'is_spin_polarized_and_im_resolved': False,
            'f_orbitals_spin': False,
            'f_orbitals_im_resolved_spin': False,
            'description': (
                "Each orbital's DOS is split into a total component and "
                "mx/my/mz magnetization density; only the total component is "
                "plotted per orbital for now."
            ),
        }

    is_im_resolved = num_columns == 10
    is_spin_polarized = num_columns == 7
    is_spin_polarized_and_im_resolved = num_columns == 19
    f_orbitals_im_resolved = num_columns == 17
    f_orbitals = contains_f_element and num_columns == 5
    no_d_orbitals = (not contains_f_element) and num_columns == 5
    f_orbitals_im_resolved_spin = num_columns == 33
    f_orbitals_spin = num_columns == 9

    if is_im_resolved:
        orbital_labels = ['s', 'py', 'pz', 'px', 'dxy', 'dyz', 'dz²', 'dxz', 'dx²-y²']
        description = (
            "lm-resolved calculation detected (LORBIT=11, 12, 13, or 14 "
            "(VASP>6)). Orbitals are resolved into individual components: "
            "px, py, pz, etc."
        )
    elif is_spin_polarized:
        orbital_labels = ['s ↑', 's ↓', 'p ↑', 'p ↓', 'd ↑', 'd ↓']
        description = (
            "Spin-polarized collinear calculation with grouped orbitals "
            "detected (LORBIT=0, 1, 2, 5 or 10, ISPIN=2). Only total p- and "
            "d-orbital contributions are available (i.e., p = px + py + pz) "
            "with respective spin states."
        )
    elif is_spin_polarized_and_im_resolved:
        orbital_labels = [
            "s ↑", "s ↓", "py ↑", "py ↓", "pz ↑", "pz ↓", "px ↑", "px ↓",
            "dxy ↑", "dxy ↓", "dyz ↑", "dyz ↓", "dz² ↑", "dz² ↓", "dxz ↑", "dxz ↓", "dx²-y² ↑", "dx²-y² ↓"
        ]
        description = (
            "lm-resolved calculation detected (LORBIT=11, 12, 13, or 14 "
            "(VASP>6)). Orbitals are resolved into individual components: "
            "px, py, pz, etc. with respective spin states."
        )
    elif f_orbitals:
        orbital_labels = ["s", "p", "d", "f"]
        description = "f-block element detected with 5 columns: s, p, d, and f contributions are available (grouped)."
    elif no_d_orbitals:
        orbital_labels = ["s", "py", "pz", "px"]
        description = (
            "Regular grouped atomic contribution detected (LORBIT=0, 1, 2, 5 "
            "or 10). s and total p-orbital contributions are available (i.e., "
            "p = px + py + pz)."
        )
    elif f_orbitals_im_resolved:
        orbital_labels = [
            's', 'py', 'pz', 'px', 'dxy', 'dyz', 'dz²', 'dxz', 'dx²-y²',
            'fx(3x²-y²)', 'fxyz', 'fyz²', 'fz³', 'fxz²', 'fx(x²-y²)', 'fx(x²-3y²)'
        ]
        description = (
            "lm-resolved calculation detected (LORBIT=11, 12, 13, or 14 "
            "(VASP>6)). Orbitals are resolved into individual components: "
            "px, py, pz, etc. up to the f orbital"
        )
    elif f_orbitals_im_resolved_spin:
        orbital_labels = [
            's ↑', 's ↓', 'py ↑', 'py ↓', 'pz ↑', 'pz ↓', 'px ↑', 'px ↓',
            'dxy ↑', 'dxy ↓', 'dyz ↑', 'dyz ↓', 'dz² ↑', 'dz² ↓', 'dxz ↑', 'dxz ↓',
            'dx²-y² ↑', 'dx²-y² ↓',
            'fx(3x²-y²) ↑', 'fx(3x²-y²) ↓',
            'fxyz ↑', 'fxyz ↓',
            'fyz² ↑', 'fyz² ↓',
            'fz³ ↑', 'fz³ ↓',
            'fxz² ↑', 'fxz² ↓',
            'fx(x²-y²) ↑', 'fx(x²-y²) ↓',
            'fx(x²-3y²) ↑', 'fx(x²-3y²) ↓'
        ]
        description = (
            "lm-resolved calculation detected (LORBIT=11, 12, 13, or 14 "
            "(VASP>6)). Orbitals are resolved into individual components: "
            "px, py, pz, etc. up to the f orbital with respective spin states."
        )
    elif f_orbitals_spin:
        orbital_labels = ['s ↑', 's ↓', 'p ↑', 'p ↓', 'd ↑', 'd ↓', 'f ↑', 'f ↓']
        description = (
            "Regular grouped atomic contribution detected (LORBIT=0, 1, 2, 5 "
            "or 10). s and total p-, d- and f-orbital contributions are "
            "available (i.e., p = px + py + pz) with respective spin states."
        )
    elif num_columns == 4:
        orbital_labels = ["s", "p", "d"]
        description = (
            "Regular grouped atomic contribution detected (LORBIT=0, 1, 2, 5 "
            "or 10). Only total p- and d-orbital contributions are available "
            "(i.e., p = px + py + pz)."
        )
    else:
        orbital_labels = []
        description = "Unknown orbital format detected."

    orbital_indices = {label: i + 1 for i, label in enumerate(orbital_labels)}
    return {
        'orbital_labels': orbital_labels,
        'orbital_indices': orbital_indices,
        'total_col_indices': list(range(1, num_columns)),
        'is_noncollinear': False,
        'is_spin_polarized': is_spin_polarized,
        'is_spin_polarized_and_im_resolved': is_spin_polarized_and_im_resolved,
        'f_orbitals_spin': f_orbitals_spin,
        'f_orbitals_im_resolved_spin': f_orbitals_im_resolved_spin,
        'description': description,
    }


def format_orbital_label(orbital):
    # 1. Subscript 3x², 3y², 3z², 3x³, etc.
    orbital_html = re.sub(r'3([xyz])²', r'<sub>3\1<sup>2</sup></sub>', orbital)
    orbital_html = re.sub(r'3([xyz])³', r'<sub>3\1<sup>3</sup></sub>', orbital_html)
    # 2. Subscript 3x, 3y, 3z (not already handled above, and not followed by <sup>)
    orbital_html = re.sub(r'3([xyz])(?![<\w])', r'<sub>3\1</sub>', orbital_html)
    # 3. Subscript px, py, pz, dxy, dxz, dyz, etc. (but not if already subscripted by 3)
    # Only subscript if not already containing a number
    orbital_html = re.sub(r'([spdf])([xyz]{1,2})²', r'\1<sub>\2<sup>2</sup></sub>', orbital_html)
    orbital_html = re.sub(r'([spdf])([xyz]{1,2})³', r'\1<sub>\2<sup>3</sup></sub>', orbital_html)
    orbital_html = re.sub(r'([spdf])([xyz]{1,2})(?![^<]*</sub>)', r'\1<sub>\2</sub>', orbital_html)
    # 4. Standalone x², y², z², x³, y³, z³
    orbital_html = re.sub(r'([xyz])²', r'<sub>\1<sup>2</sup></sub>', orbital_html)
    orbital_html = re.sub(r'([xyz])³', r'<sub>\1<sup>3</sup></sub>', orbital_html)
    # 5. Subscript any remaining single x, y, z (not already subscripted)
    orbital_html = re.sub(r'(?<!<sub>)\b([xyz])\b(?!<sup>|</sub>)', r'<sub>\1</sub>', orbital_html)
    # 6. Subscript minus
    orbital_html = orbital_html.replace('-', '<sub>-</sub>')
    # 7. Optionally subscript parentheses
    orbital_html = orbital_html.replace('(', '<sub>(</sub>').replace(')', '<sub>)</sub>')
    return f"<i>{orbital_html}</i>"

def parse_doscar_and_plot(doscar_filename, poscar_filename, xmin=None, xmax=None, ymin=None, ymax=None, legend_y=0.26, custom_colors=None, plot_type="total", spin_polarized=False, selected_atoms=None, toggled_atoms=None, show_idos=False, show_titles=None, show_axis_scale=None, display_spins=None, legend_order=None):

    # Ensure custom_colors is initialized
    # custom_colors = {color_id['index']: color for color_id, color in zip(color_ids, selected_colors) if color is not None}

    # toggled_atoms = {toggle_id['index']: 'total' in toggled for toggle_id, toggled in zip(toggle_ids, toggled_totals)}

    with open(doscar_filename, 'r') as f:
        lines = f.readlines()

    num_atoms, num_points, fermi_energy, lines_per_point = read_doscar_header(lines)

    # Extract the first block (Total DOS)
    first_block = np.array([
        [float(value) for value in line.split()]  # Parse values correctly, including scientific notation
        for line in lines[6:6 + num_points]
    ])

    # Calculate energy and total DOS
    energy = first_block[:, 0] - fermi_energy  # Subtract Fermi energy from column 1

    # Check if the first block indicates spin polarization (must be done early)
    num_columns_first_block = len(lines[6].split())
    has_spin_data = num_columns_first_block == 5  # Energy, DOS_up, DOS_down, integrated_DOS_up, integrated_DOS_down

    # Read atom contributions from atom blocks (lines_per_point > 1 when VASP
    # wraps very wide rows -- e.g. non-collinear + lm-resolved + f -- across
    # multiple physical lines; see read_doscar_header)
    atom_dos_blocks = read_atom_dos_blocks(lines, num_atoms, num_points, fermi_energy, lines_per_point)

    # Get POSCAR data early, since classify_orbitals needs atom_types to
    # disambiguate a couple of column-count cases
    with open(poscar_filename, 'r') as f:
        poscar_lines = f.readlines()
    atom_types = poscar_lines[5].split()
    atom_counts = list(map(int, poscar_lines[6].split()))

    # Dynamically determine the number of columns in the atom blocks, and map
    # that to orbital labels/indices (handles collinear and non-collinear
    # DOSCAR layouts -- see classify_orbitals)
    num_columns = atom_dos_blocks[0].shape[1]
    orbital_info = classify_orbitals(num_columns, atom_types)
    orbital_labels = orbital_info['orbital_labels']
    orbital_indices = orbital_info['orbital_indices']
    total_col_indices = orbital_info['total_col_indices']
    is_spin_polarized = orbital_info['is_spin_polarized']
    is_spin_polarized_and_im_resolved = orbital_info['is_spin_polarized_and_im_resolved']
    f_orbitals_spin = orbital_info['f_orbitals_spin']
    f_orbitals_im_resolved_spin = orbital_info['f_orbitals_im_resolved_spin']

    # Sum all atom contributions to calculate total DOS. For non-collinear
    # data, total_col_indices only picks out each orbital's total (charge)
    # sub-column, skipping its mx/my/mz magnetization sub-columns -- summing
    # those in would mix signed magnetization into a particle-count total.
    total_dos = np.zeros(num_points)
    for block in atom_dos_blocks:
        total_dos += np.sum(block[:, total_col_indices], axis=1)

    # Dynamically calculate xmax based on the maximum DOS value within the energy range
    if xmax is None:
        if display_spins and 'display_spins' in display_spins and has_spin_data:
            # For spin display, calculate based on individual spin components
            dos_up_in_range = first_block[:, 1][(energy >= (ymin if ymin is not None else -np.inf)) & (energy <= (ymax if ymax is not None else np.inf))]
            dos_down_in_range = first_block[:, 2][(energy >= (ymin if ymin is not None else -np.inf)) & (energy <= (ymax if ymax is not None else np.inf))]
            max_dos = max(np.max(dos_up_in_range) if len(dos_up_in_range) > 0 else 0,
                         np.max(dos_down_in_range) if len(dos_down_in_range) > 0 else 0)
            base_xmax = 1.1 * max_dos if max_dos > 0 else 28
            xmax = base_xmax
            xmin = -base_xmax if xmin is None else xmin
        else:
            # Regular calculation for non-spin display
            dos_in_range = total_dos[(energy >= (ymin if ymin is not None else -np.inf)) & (energy <= (ymax if ymax is not None else np.inf))]
            xmax = 1.1 * np.max(dos_in_range) if len(dos_in_range) > 0 else 28  # Default to 28 if no values are found

    # Check if we should display spins separately
    display_spin_separated = display_spins and 'display_spins' in display_spins and has_spin_data

    # Sort atom types by Mendeleev numbers
    atom_types_sorted = sorted(atom_types, key=lambda x: mendeleev_numbers.get(x, float('inf')))

    # Assign colors based on order
    default_colors = ['blue', 'red', 'green']
    color_map = {atom: default_colors[i % len(default_colors)] for i, atom in enumerate(atom_types_sorted)}

    # Build traces for the final figure
    traces = []
    total_traces = []  # Separate storage for total traces

    # Get folder name for display
    folder_path = os.path.dirname(os.path.abspath(doscar_filename))
    folder_name = os.path.basename(folder_path)

    def subscript_numbers(text):
        sub_map = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
        return re.sub(r'(\d+)', lambda m: m.group(0).translate(sub_map), text)

    folder_name_unicode = subscript_numbers(folder_name)

    # Prepare total DOS traces (but don't add to main traces yet)
    if toggled_atoms is None or toggled_atoms.get('Total', True):
        if display_spin_separated and has_spin_data:
            # For spin-polarized display, use the first block data
            dos_up = first_block[:, 1]  # DOS (↑)
            dos_down = first_block[:, 2]  # DOS (↓)
            
            # Plot spin up (positive side)
            total_traces.append(go.Scatter(
                x=dos_up,
                y=energy,
                mode='lines',
                name='Total ↑',
                line=dict(color=custom_colors.get('Total', 'black'), width=2.25),
            ))
            
            # Plot spin down (negative side)
            total_traces.append(go.Scatter(
                x=-dos_down,  # Negative for left side
                y=energy,
                mode='lines',
                name='Total ↓',
                line=dict(color=custom_colors.get('Total', 'black'), width=2.25, dash='dash'),
                showlegend=False,  # Hide from legend since spin up (↑) already indicates spin polarization
            ))
        else:
            # Regular total DOS plot
            total_traces.append(go.Scatter(
                x=total_dos,  # Use the atom-summed total DOS
                y=energy,  # Use the energy values
                mode='lines',
                name='Total',
                line=dict(color=custom_colors.get('Total', 'black'), width=2.25),
            ))

    # Handle atomic contributions if selected_atoms or toggled_atoms is provided
    if selected_atoms or toggled_atoms:
        # atom_dos_blocks was already parsed above (wrap-aware); no need to re-read it here.

        # Create a mapping of atom type to its starting indices and counts
        atom_type_ranges = {}
        start_index = 0
        for atom_type, count in zip(atom_types, atom_counts):
            end_index = start_index + count
            atom_type_ranges[atom_type] = (start_index, end_index)
            start_index = end_index

        # Determine plotting order - use legend_order if provided, otherwise Mendeleev order
        if legend_order and len(legend_order) > 1:
            # Use custom legend order, but only include atom types that exist in the system
            atom_order = [atom for atom in legend_order if atom in atom_type_ranges]
            # Add any missing atom types at the end
            for atom_type in atom_types_sorted:
                if atom_type not in atom_order:
                    atom_order.append(atom_type)
        else:
            # Use default Mendeleev order
            atom_order = atom_types_sorted
        
        # Plot in the determined order
        for atom_type in atom_order:
            if atom_type not in atom_type_ranges:
                continue
            start_index, end_index = atom_type_ranges[atom_type]

    
            # Plot total contributions if toggled
            if toggled_atoms and toggled_atoms.get(atom_type, False):
                total_contribution = np.zeros(num_points)
                for atom_index in range(start_index, end_index):
                    total_contribution += np.sum(atom_dos_blocks[atom_index][:, total_col_indices], axis=1)  # Sum orbital totals (skips mx/my/mz for non-collinear data)
                
                if display_spin_separated and has_spin_data and (is_spin_polarized or is_spin_polarized_and_im_resolved or f_orbitals_spin or f_orbitals_im_resolved_spin):
                    # For spin-polarized atomic contributions, split into up and down
                    total_contribution_up = np.zeros(num_points)
                    total_contribution_down = np.zeros(num_points)
                    
                    for atom_index in range(start_index, end_index):
                        if is_spin_polarized:  # s↑, s↓, p↑, p↓, d↑, d↓
                            total_contribution_up += atom_dos_blocks[atom_index][:, 1] + atom_dos_blocks[atom_index][:, 3] + atom_dos_blocks[atom_index][:, 5]  # s↑ + p↑ + d↑
                            total_contribution_down += atom_dos_blocks[atom_index][:, 2] + atom_dos_blocks[atom_index][:, 4] + atom_dos_blocks[atom_index][:, 6]  # s↓ + p↓ + d↓
                        elif is_spin_polarized_and_im_resolved:  # Individual orbitals with spin
                            # Sum all up spins (odd indices: 1, 3, 5, 7, 9, 11, 13, 15, 17)
                            total_contribution_up += np.sum(atom_dos_blocks[atom_index][:, 1::2], axis=1)
                            # Sum all down spins (even indices: 2, 4, 6, 8, 10, 12, 14, 16, 18)
                            total_contribution_down += np.sum(atom_dos_blocks[atom_index][:, 2::2], axis=1)
                        elif f_orbitals_spin:  # s↑, s↓, p↑, p↓, d↑, d↓, f↑, f↓
                            total_contribution_up += atom_dos_blocks[atom_index][:, 1] + atom_dos_blocks[atom_index][:, 3] + atom_dos_blocks[atom_index][:, 5] + atom_dos_blocks[atom_index][:, 7]
                            total_contribution_down += atom_dos_blocks[atom_index][:, 2] + atom_dos_blocks[atom_index][:, 4] + atom_dos_blocks[atom_index][:, 6] + atom_dos_blocks[atom_index][:, 8]
                        elif f_orbitals_im_resolved_spin:  # Individual f orbitals with spin
                            total_contribution_up += np.sum(atom_dos_blocks[atom_index][:, 1::2], axis=1)
                            total_contribution_down += np.sum(atom_dos_blocks[atom_index][:, 2::2], axis=1)
                    
                    # Plot spin up
                    traces.append(go.Scatter(
                        x=total_contribution_up,
                        y=atom_dos_blocks[start_index][:, 0],
                        mode='lines',
                        name=f"{atom_type} ↑",
                        line=dict(color=custom_colors.get(atom_type, 'gray'), width=2.5)
                    ))
                    
                    # Plot spin down (negative)
                    traces.append(go.Scatter(
                        x=-total_contribution_down,
                        y=atom_dos_blocks[start_index][:, 0],
                        mode='lines',
                        name=f"{atom_type} ↓",
                        line=dict(color=custom_colors.get(atom_type, 'gray'), width=2.5, dash='dash'),
                        showlegend=False,  # Hide from legend since spin up (↑) already indicates spin polarization
                    ))
                else:
                    # Regular atomic total plot
                    traces.append(go.Scatter(
                        x=total_contribution,
                        y=atom_dos_blocks[start_index][:, 0],  # Energy remains the same
                        mode='lines',
                        name=f"{atom_type}",
                        line=dict(color=custom_colors.get(atom_type, 'gray'), width=2.5)
                    ))

            # Plot selected orbital contributions
            if selected_atoms and atom_type in selected_atoms:
                for orbital in selected_atoms[atom_type]:
                    orbital_index = orbital_indices.get(orbital, None)
                    if orbital_index is not None:
                        summed_contribution = np.zeros(num_points)
                        for atom_index in range(start_index, end_index):
                            summed_contribution += atom_dos_blocks[atom_index][:, orbital_index]
                        traces.append(go.Scatter(
                            x=summed_contribution,
                            y=atom_dos_blocks[start_index][:, 0],  # Energy remains the same
                            mode='lines',
                            name=f"{atom_type} ({format_orbital_label(orbital)})",
                            line=dict(color=custom_colors.get(atom_type, 'gray'), width=1.5)
                        ))

    # Organize traces according to legend order
    ordered_traces = []
    trace_dict = {}
    
    # Create a dictionary to store traces by their primary identifier
    for trace in total_traces:
        if 'Total' not in trace_dict:
            trace_dict['Total'] = []
        trace_dict['Total'].append(trace)
    
    for trace in traces:
        # Extract atom type from trace name (handle both "Atom" and "Atom (orbital)" formats)
        trace_name = trace.name
        if '(' in trace_name and ')' in trace_name:
            if trace_name.endswith('↑') or trace_name.endswith('↓'):
                # Handle spin cases like "Fe (↑)" or "Fe (↓)"
                atom_type = trace_name.split(' (')[0]
            else:
                # Handle orbital cases like "Fe (dxy)"
                atom_type = trace_name.split(' (')[0]
        else:
            atom_type = trace_name
        
        if atom_type not in trace_dict:
            trace_dict[atom_type] = []
        trace_dict[atom_type].append(trace)
    
    # Add traces in the order specified by legend_order
    if legend_order and len(legend_order) > 1:
        for item in legend_order:
            if item in trace_dict:
                ordered_traces.extend(trace_dict[item])
        # Add any remaining traces not in legend_order
        for key, trace_list in trace_dict.items():
            if key not in legend_order:
                ordered_traces.extend(trace_list)
    else:
        # If no legend order specified, add Total first, then others
        if 'Total' in trace_dict:
            ordered_traces.extend(trace_dict['Total'])
        for key, trace_list in trace_dict.items():
            if key != 'Total':
                ordered_traces.extend(trace_list)

    # Create the figure from ordered traces
    fig = go.Figure()
    for trace in ordered_traces:
        fig.add_trace(trace)

    fig.add_shape(
        type="line",
        x0=xmin if xmin is not None else 0,
        x1=xmax,  # Use the dynamically calculated xmax
        y0=0,
        y1=0,
        line=dict(
            color="black",
            width=2,
            dash="dash",
        ),
    )

    # Use user-specified legend position
    legend_y_adjusted = legend_y

    fig.update_layout(
        font=dict(family="DejaVu Sans, Arial, sans-serif", size=20, color='black'),
        title=dict(
            text=folder_name_unicode + " DOS" if 'plot_title' in show_titles else "",
            x=0.5,
            xanchor='center',
            y=0.98,
            font=dict(size=20, family="DejaVu Sans, Arial, sans-serif"),
        ),
        xaxis=dict(
            title=dict(
                text='DOS' if 'x_title' in show_titles else '',
                font=dict(size=20, family="DejaVu Sans, Arial, sans-serif"),
            ),
            range=[xmin if xmin is not None else (0 if not (display_spins and 'display_spins' in display_spins and has_spin_data) else -xmax), xmax],  # Use symmetric range for spin display
            showgrid=False,
            zeroline=True,
            zerolinewidth=3,
            zerolinecolor='black',
            showticklabels='x_scale' in show_axis_scale,  # Show x-axis tick labels based on show_axis_scale
            ticks='outside' if 'x_scale' in show_axis_scale else '',  # Show ticks outside if x_scale is in show_axis_scale
            tickwidth=2,
            ticklen=8,
            tickcolor='black',
            tickfont=dict(size=20, family="DejaVu Sans, Arial, sans-serif"),
            automargin=True  # Ensure proper spacing for the x-axis title
        ),
        yaxis=dict(
            title=dict(
                text='Energy (eV)' if 'y_title' in show_titles else '',
                font=dict(size=20, family="DejaVu Sans, Arial, sans-serif"),
            ),
            range=[ymin if ymin is not None else -8, ymax if ymax is not None else 2],
            showgrid=False,
            zeroline=False,
            showticklabels='y_scale' in show_axis_scale,  # Show y-axis tick labels based on show_axis_scale
            ticks='outside' if 'y_scale' in show_axis_scale else '',  # Show ticks outside if y_scale is in show_axis_scale
            tickwidth=2,
            ticklen=8,
            tickcolor='black',
            tickfont=dict(size=20, family="DejaVu Sans, Arial, sans-serif")
        ),
        legend=dict(
            x=0.95,
            y=legend_y_adjusted,
            xanchor='right',
            yanchor='top'
        ),
        plot_bgcolor='white',
        paper_bgcolor='white',
        margin=dict(l=50, r=50, t=50, b=50),
        height=725,
        width=400,
    )

    fig.add_annotation(
        xref="x",
        yref="y",
        x=xmax if xmax is not None else 28,
        y=0.2,
        text="<i>E</i><sub><i>F</i></sub>",
        showarrow=False,
        font=dict(size=20, family="DejaVu Sans, Arial, sans-serif", color="black"),
        xanchor="left",
        yanchor="top"
    )

    fig.add_shape(
        type="rect",
        x0=0, y0=0, x1=1, y1=1,
        xref="paper", yref="paper",
        line=dict(color="black", width=2),
    )

    return fig
