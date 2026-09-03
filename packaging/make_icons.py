"""
Generate the app icon assets (icon.icns for macOS, icon.ico for Windows)
from a single high-resolution PNG drawn here with Pillow.

Usage:
    python packaging/make_icons.py

Run this whenever the icon design changes; the outputs are committed to the
repo (packaging/icon.icns, packaging/icon.ico) so a normal build doesn't need
to regenerate them.
"""

import math
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SIZE = 1024

BG_TOP = (61, 118, 237)      # matches --primary in assets/style.css
BG_BOTTOM = (125, 168, 255)


def draw_base_icon() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded-square gradient background (macOS-style "squircle" corner radius).
    radius = int(SIZE * 0.225)
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=radius, fill=255)

    gradient = Image.new("RGBA", (SIZE, SIZE))
    for y in range(SIZE):
        t = y / (SIZE - 1)
        r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
        for x in range(SIZE):
            gradient.putpixel((x, y), (r, g, b, 255))
    img.paste(gradient, (0, 0), mask)
    draw = ImageDraw.Draw(img)

    # DOS-spectrum glyph: baseline + a couple of asymmetric peaks, echoing
    # assets/icon.svg used in the in-app header badge.
    pad = SIZE * 0.24
    baseline_y = SIZE * 0.72
    axis_top = SIZE * 0.22

    line_w = max(6, int(SIZE * 0.028))
    color = (255, 255, 255, 255)

    # Axis (L-shape).
    draw.line([(pad, axis_top), (pad, baseline_y)], fill=color, width=line_w, joint="curve")
    draw.line([(pad, baseline_y), (SIZE - pad * 0.7, baseline_y)], fill=color, width=line_w, joint="curve")

    # Spectrum curve, built from a handful of control points and rendered as
    # a smooth-ish polyline (kept dependency-free: no numpy/scipy needed for
    # a one-off build script).
    xs = [pad] + [pad + (SIZE - 2 * pad) * f for f in (0.12, 0.30, 0.46, 0.64, 0.8, 0.95)]
    ys_frac = [1.0, 0.35, 0.75, 0.55, 0.08, 0.5, 0.62]  # 1.0 = baseline, 0 = axis_top
    points = []
    for i, x in enumerate(xs):
        f = ys_frac[i] if i < len(ys_frac) else 1.0
        y = baseline_y - f * (baseline_y - axis_top)
        points.append((x, y))
    # Smooth the polyline slightly via simple Catmull-Rom-ish subdivision.
    smooth_points = []
    pts = [points[0]] + points + [points[-1]]
    steps = 24
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for s in range(steps):
            t = s / steps
            t2 = t * t
            t3 = t2 * t
            x = 0.5 * (
                (2 * p1[0])
                + (-p0[0] + p2[0]) * t
                + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3
            )
            y = 0.5 * (
                (2 * p1[1])
                + (-p0[1] + p2[1]) * t
                + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3
            )
            smooth_points.append((x, y))
    smooth_points.append(points[-1])

    draw.line(smooth_points, fill=color, width=line_w, joint="curve")
    r = line_w * 0.75
    for x, y in (smooth_points[0], smooth_points[-1]):
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)

    return img


def save_ico(img: Image.Image) -> None:
    ico_path = os.path.join(HERE, "icon.ico")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(ico_path, format="ICO", sizes=sizes)
    print(f"wrote {ico_path}")


def save_icns(img: Image.Image) -> None:
    icns_path = os.path.join(HERE, "icon.icns")

    if sys.platform == "darwin" and shutil.which("iconutil"):
        with tempfile.TemporaryDirectory() as tmp:
            iconset = os.path.join(tmp, "icon.iconset")
            os.makedirs(iconset)
            specs = [
                ("icon_16x16.png", 16),
                ("icon_16x16@2x.png", 32),
                ("icon_32x32.png", 32),
                ("icon_32x32@2x.png", 64),
                ("icon_128x128.png", 128),
                ("icon_128x128@2x.png", 256),
                ("icon_256x256.png", 256),
                ("icon_256x256@2x.png", 512),
                ("icon_512x512.png", 512),
                ("icon_512x512@2x.png", 1024),
            ]
            for name, size in specs:
                img.resize((size, size), Image.LANCZOS).save(os.path.join(iconset, name))
            subprocess.run(
                ["iconutil", "-c", "icns", iconset, "-o", icns_path],
                check=True,
            )
        print(f"wrote {icns_path}")
    else:
        print("iconutil not available (not on macOS) — skipping icon.icns; "
              "build icon.icns on a Mac, or via `iconutil`, before packaging the macOS app.")


def main():
    img = draw_base_icon()
    img.resize((512, 512), Image.LANCZOS).save(os.path.join(HERE, "icon_preview.png"))
    save_ico(img)
    save_icns(img)


if __name__ == "__main__":
    main()
