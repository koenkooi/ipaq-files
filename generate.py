#!/usr/bin/env python3
"""Generate editable handheld frames; see --help for selection and output options."""
# SPDX-FileCopyrightText: 2026 Koen Kooi
# SPDX-License-Identifier: GPL-2.0-or-later

import argparse
from contextlib import nullcontext
from dataclasses import dataclass, replace
from functools import partial
from html import escape
import math
import os
from pathlib import Path
import random
import re
import sys
from types import SimpleNamespace
from typing import Callable, Optional
from uuid import uuid4
import xml.etree.ElementTree as ET


SVG_NS = "http://www.w3.org/2000/svg"
REPOSITORY = Path(__file__).resolve().parent


def f(value):
    """Historical iPAQ precision; changing it changes the generated artwork."""
    result = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if result == "-0" else result


def fmt3(value):
    """Zaurus paths retain their original three-decimal precision."""
    return f"{value:.3f}".rstrip("0").rstrip(".") or "0"


class Fonts:
    """One font cache per generation run, with no system font substitution."""

    faces = {
        "regular": "OpenSans_Regular.ttf",
        "bold": "OpenSans_Bold.ttf",
        "jp": "NotoSansCJKjp_Regular.otf",
    }

    def __init__(self, directory):
        self.directory = Path(directory)
        self.loaded = {}

    def __enter__(self):
        try:
            from fontTools.ttLib import TTFont
            from fontTools.pens.boundsPen import BoundsPen
            from fontTools.pens.svgPathPen import SVGPathPen
            from fontTools.pens.transformPen import TransformPen
        except ImportError as error:
            raise RuntimeError("fontTools is required: python3 -m pip install fonttools") from error
        self.TTFont = TTFont
        self.BoundsPen = BoundsPen
        self.SVGPathPen = SVGPathPen
        self.TransformPen = TransformPen
        return self

    def __exit__(self, *exc):
        for font in self.loaded.values():
            font.close()

    def load(self, filename):
        if filename not in self.loaded:
            path = self.directory / filename
            if not path.is_file():
                raise FileNotFoundError(f"required font not found: {path}")
            self.loaded[filename] = self.TTFont(path)
        return self.loaded[filename]

    def glyph_run(self, text, filename, cap, spacing=0):
        font = self.load(filename)
        glyphs = font.getGlyphSet()
        cmap = font.getBestCmap()
        missing = [char for char in text if ord(char) not in cmap]
        if missing:
            raise ValueError(f"{filename}: missing glyphs for {missing!r}")
        cap_height = getattr(font["OS/2"], "sCapHeight", 0)
        if cap_height <= 0:
            raise ValueError(f"{filename}: missing or invalid cap height")
        sy = cap / cap_height
        measure = self.BoundsPen(glyphs)
        positions = []
        position = 0
        for char in text:
            name = cmap[ord(char)]
            positions.append((name, position))
            glyphs[name].draw(self.TransformPen(measure, (1, 0, 0, 1, position, 0)))
            position += font["hmtx"][name][0] + spacing / sy
        return glyphs, positions, measure.bounds, sy

    def draw_run(self, glyphs, positions, sx, sy, left, baseline, formatter):
        pen = self.SVGPathPen(glyphs, ntos=formatter)
        for name, position in positions:
            glyphs[name].draw(self.TransformPen(
                pen, (sx, 0, 0, -sy, left + position * sx, baseline)))
        return pen.getCommands()

    def word_path(self, text, filename, cap, x, baseline, anchor, width):
        glyphs, positions, bounds, sy = self.glyph_run(text, filename, cap)
        if bounds is None:
            raise ValueError(f"{filename}: wordmark {text!r} has no outline")
        xmin, _, xmax, _ = bounds
        sx = width / (xmax - xmin) if width else sy
        ink_width = (xmax - xmin) * sx
        left = {"start": x, "end": x - ink_width, "middle": x - ink_width / 2}[anchor] - xmin * sx
        return self.draw_run(glyphs, positions, sx, sy, left, baseline, f)

    def text_path(self, text, x, baseline, cap, *, face="regular", width=None,
                  spacing=0, fill="#343738", extra=""):
        glyphs, positions, bounds, sy = self.glyph_run(text, self.faces[face], cap, spacing)
        if bounds is None:
            return ""
        left, _, right, _ = bounds
        sx = width / (right - left) if width else sy
        origin = x - (right + left) * sx / 2
        path = self.draw_run(glyphs, positions, sx, sy, origin, baseline, fmt3)
        return f'<path d="{path}" fill="{fill}" {extra}/>'


def inverse3(matrix):
    """Inverse of a 3 x 3 projective transform, using cofactors."""
    a, b, c = matrix[0]
    d, e, g = matrix[1]
    h, i, j = matrix[2]
    adjugate = ((e*j-g*i, c*i-b*j, b*g-c*e),
                (g*h-d*j, a*j-c*h, c*d-a*g),
                (d*i-e*h, b*h-a*i, a*e-b*d))
    determinant = a * adjugate[0][0] + b * adjugate[1][0] + c * adjugate[2][0]
    if abs(determinant) < 1e-15:
        raise ValueError("singular projective transform")
    return tuple(tuple(value / determinant for value in row) for row in adjugate)


def spline(points, closed=True, tension=6.0):
    """Catmull-Rom through the points, as cubic Bezier segments."""
    n = len(points)
    d = f'M{f(points[0][0])},{f(points[0][1])}'
    last = n if closed else n - 1
    for i in range(last):
        p0 = points[(i - 1) % n] if closed or i > 0 else points[i]
        p1, p2 = points[i], points[(i + 1) % n]
        p3 = points[(i + 2) % n] if closed or i + 2 < n else p2
        c1 = (p1[0] + (p2[0] - p0[0]) / tension, p1[1] + (p2[1] - p0[1]) / tension)
        c2 = (p2[0] - (p3[0] - p1[0]) / tension, p2[1] - (p3[1] - p1[1]) / tension)
        d += f' C{f(c1[0])},{f(c1[1])} {f(c2[0])},{f(c2[1])} {f(p2[0])},{f(p2[1])}'
    return d + (' Z' if closed else '')


def mirror(half, cx):
    """Closed outline from a right-half profile listed top to bottom."""
    right = [(cx + h, y) for h, y in half]
    left = [(cx - h, y) for h, y in reversed(half) if h != 0]
    return right + left


IPAQ_BODY_HALF = [
    (0, 77), (150, 76.5), (245, 72.5), (280, 75.8), (310, 79.8), (330, 82.6), (350, 86),
    (370, 90), (381, 94), (388.5, 100.5), (391.5, 110), (392.3, 125), (390.3, 300),
    (388.6, 400), (387.3, 600), (387, 800), (385, 1000), (383.3, 1100), (381.1, 1200),
    (379.5, 1220), (377, 1236), (371.5, 1246), (362, 1255.5), (350, 1265), (330, 1278.5), (310, 1292.5),
    (270, 1316), (230, 1337), (190, 1353.5), (150, 1369.5), (110, 1379.3), (60, 1386.8),
    (0, 1389.6),
]


def build_h3900(fonts):
    """Draw the h3900 from measured photo coordinates."""
    S = 0.875                       # SVG units per photo px
    VB_X, VB_Y = -0.3125, -0.25
    CSS_W, CSS_H = 366, 585
    VB_W, VB_H = CSS_W * 2.1875, CSS_H * 2.1875
    GLASS_U = (137.5, 244.75, 525, 700)   # screen rect in units: 240x320 px at 2.1875
    GX, GY, GW, GH = 275, 262, 600, 800  # the same rect in photo px
    TX = GLASS_U[0] - GX * S
    TY = GLASS_U[1] - GY * S

    # ---- measured geometry (photo px) ------------------------------------------
    CX = 575          # device centre line (screen and nav pad centre)
    CAPX = 572        # cap centre, measured 3 px left of the screen centre
    BX = 591          # body centre line: both silhouettes in the owner's photos sit 16 px right of CX

    # Right half of the body silhouette as (half-width from BX, y), top to bottom; mirrored.
    # Measured on the rectified front photo (mid-level luminance crossing, left and
    # right averaged about BX, less 1.2 px for the 1.7-unit outline stroke); the tape
    # photo gives the same width within 1 %.
    BODY_HALF = IPAQ_BODY_HALF
    CURL = 18         # width of the rounded side band, where the face turns into the sides
    CHIN = 20         # height of the lower band, where the face turns under


    # Black top cap, right half (half-width from CAPX, y); mirrored.
    CAP_HALF = [
        (0, 22), (92, 29), (160, 40), (215, 56), (240, 65), (255, 71), (260, 76),
        (258, 90), (252, 130), (246, 170), (241, 192), (236, 199), (225, 202),
        (150, 205), (60, 208), (0, 209),
    ]
    CAP_RIM = 18      # width of the cap's side edges, which are the two LED windows
    GRILLE = dict(y0=88, y1=181, n=6, half=[90, 94, 94, 94, 94, 90])
    POWER = (740, 120)            # chrome ring r 31, face r 22
    WINDOW = (367.5, 159, 10)   # small round window on the cap, lower left
    MIC = (375, 92, 106)          # two short slits

    # Screen opening: 3 px dark border around the glass, 7 px bevel outside it.
    BORDER, BEVEL = 3, 7

    # Application buttons (centre x, y, glyph) and their dishes; symmetric about CX.
    BUTTONS = [(CX - 255, 1226, 'calendar'), (CX - 189, 1180, 'contacts'),
               (CX + 189, 1180, 'mail'), (CX + 255, 1226, 'task')]
    DISH_R, RING_R, FACE_R = 44, 29, 27

    NAV = dict(cx=CX, cy=1240, ring=(170, 80), gap=(150, 70), pad=(136, 61), boss=(215, 105))

    # Wordmarks: text, font, cap-height target, anchor x, baseline y, anchor, fill.

    WORDS = [
        ('iPAQ', 'Mukta_Regular.ttf', 24, 280, 246, 'start', '#2a2b2c', None),
        ('Pocket PC', 'Mukta_Regular.ttf', 21, 859, 243, 'end', '#2a2b2c', 129),
        ('COMPAQ', 'OpenSans_BoldItalic.ttf', 24, CAPX, 72, 'middle', '#f1f2f3', 169),
    ]
    # -----------------------------------------------------------------------------





    def pts(seq):
        return ' '.join(f'{f(x)},{f(y)}' for x, y in seq)








    # The left shoulder sits 3-5 px lower than the right in the photo and runs
    # straight into the record housing's chamfer; these replace the mirrored points there.
    LEFT_TOP = [(245, 75), (280, 77.6), (310, 81.5), (330, 85.5), (350, 89.5), (370, 94.3),
                (381, 97.6), (388, 102), (391.5, 111), (392.3, 125)]


    def body_outline():
        """Closed outline: right half from BODY_HALF, left half mirrored except the shoulder (LEFT_TOP)."""
        right = [(BX + h, y) for h, y in BODY_HALF]
        left = [(BX - h, y) for h, y in reversed(BODY_HALF) if h != 0 and not (y <= 125 and h >= 245)]
        k = next(n for n, (_, y) in enumerate(left) if y < 300)
        return right + left[:k] + [(BX - h, y) for h, y in reversed(LEFT_TOP)] + left[k:]


    def body_half_at(y):
        """Half-width of the body at height y (linear between the profile points)."""
        pts = [(h, yy) for h, yy in BODY_HALF if yy >= 100]
        for (h0, y0), (h1, y1) in zip(pts, pts[1:]):
            if y0 <= y <= y1:
                return h0 + (h1 - h0) * (y - y0) / (y1 - y0)
        return pts[-1][0]


    # Record button housing, left side, as absolute photo px points (measured):
    # chamfered top corner, outer edge x 173.5 from y 128 to 195, back into the side by y 280.
    RECORD_PTS = [(262, 85.5), (232, 91.5), (214, 96.5), (206.5, 99.2), (199, 102), (192.5, 105.7), (186, 109.5), (180.5, 114.5), (176.5, 120.5), (174.5, 128),
                  (173.5, 150), (173.8, 190), (176.5, 212), (182, 234), (189.5, 252),
                  (196.5, 268), (BX - 390.2, 290), (BX - 384, 288), (BX - 378, 150), (BX - 350, 100)]


    def cap_outline(inset=0.0):
        half = []
        for h, y in CAP_HALF:
            if y < 70:
                half.append((max(h - inset * 0.6, 0) if h else 0, y + inset * 0.35))
            elif y > 200:
                half.append((max(h - inset, 0) if h else 0, y - inset * 0.4))
            else:
                half.append((h - inset, y))
        return mirror(half, CAPX)


    word_path = fonts.word_path


    def lens(x0, y0, x1, y1, w):
        """A thin stroke tapering to points at both ends."""
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        dx, dy = x1 - x0, y1 - y0
        ln = (dx * dx + dy * dy) ** 0.5
        nx, ny = -dy / ln * w, dx / ln * w
        return (f'M{f(x0)},{f(y0)} Q{f(mx + nx)},{f(my + ny)} {f(x1)},{f(y1)} '
            f'Q{f(mx - nx)},{f(my - ny)} {f(x0)},{f(y0)} Z')


    GLYPHS = {
        # Pocket PC application glyphs, drawn on a 20x20 grid centred on the button.
        'calendar': '''<g fill="#111" transform="translate(-9,-8)">
        <rect width="18" height="4" rx="1"/>
        <rect y="5.5" width="4.2" height="3.4"/><rect x="4.6" y="5.5" width="4.2" height="3.4"/><rect x="9.2" y="5.5" width="4.2" height="3.4"/><rect x="13.8" y="5.5" width="4.2" height="3.4"/>
        <rect y="9.8" width="4.2" height="3.4"/><rect x="4.6" y="9.8" width="4.2" height="3.4"/><rect x="9.2" y="9.8" width="4.2" height="3.4"/><rect x="13.8" y="9.8" width="4.2" height="3.4"/>
        <rect y="14.1" width="4.2" height="3.4"/><rect x="4.6" y="14.1" width="4.2" height="3.4"/><rect x="9.2" y="14.1" width="4.2" height="3.4"/>
      </g>''',
        'contacts': '''<g transform="translate(-10,-9)">
        <rect width="20" height="18" rx="1.5" fill="#111"/>
        <circle cx="6" cy="6" r="2.6" fill="#cfd0d2"/>
        <path d="M2,14.5 Q2,9.6 6,9.6 Q10,9.6 10,14.5 Z" fill="#cfd0d2"/>
        <rect x="12" y="4" width="6" height="1.8" fill="#cfd0d2"/><rect x="12" y="8" width="6" height="1.8" fill="#cfd0d2"/><rect x="12" y="12" width="6" height="1.8" fill="#cfd0d2"/>
      </g>''',
        'mail': '''<g transform="translate(-10.5,-7.5)" fill="none" stroke="#111" stroke-width="2.2" stroke-linejoin="round">
        <rect width="21" height="15" rx="1"/>
        <path d="M0,0 L10.5,8.5 L21,0 M0,15 L8,7 M21,15 L13,7"/>
      </g>''',
        'task': '''<g fill="none" stroke="#111" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
        <path d="M-7,6 A8.5,8.5 0 1 1 6.5,-6.5"/>
        <path d="M1.5,-9.5 L7,-6.6 L4.4,-0.8"/>
      </g>''',
    }


    def build():
        body = spline(body_outline())
        # The housing widens the top-left corner: it leaves the shoulder's top edge,
        # rounds the corner out to the bulge and rejoins the side below.
        record = spline(RECORD_PTS, tension=6.0)
        cap = spline(cap_outline(), tension=6.0)
        cap_in = spline(cap_outline(CAP_RIM), tension=6.0)
        side = [(h, y) for h, y in CAP_HALF if 68 <= y <= 200]
        strip = [(h, y) for h, y in side] + [(h - CAP_RIM, y) for h, y in reversed(side)]
        led_r = spline([(CAPX + h, y) for h, y in strip], tension=8.0)
        led_l = spline([(CAPX - h, y) for h, y in strip], tension=8.0)
        hl = [(h - CAP_RIM * 0.45, y) for h, y in side[1:-1]]
        led_hl_r = spline([(CAPX + h, y) for h, y in hl], closed=False)
        led_hl_l = spline([(CAPX - h, y) for h, y in hl], closed=False)
        o0 = (GX - BORDER - BEVEL, GY - BORDER - BEVEL, GX + GW + BORDER + BEVEL, GY + GH + BORDER + BEVEL)
        o1 = (GX - BORDER, GY - BORDER, GX + GW + BORDER, GY + GH + BORDER)
        n = NAV
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{CSS_W}" height="{CSS_H}" '
            f'viewBox="{VB_X!r} {VB_Y!r} {VB_W!r} {VB_H!r}">\n')
        group = f'<g transform="matrix({S} 0 0 {S} {f(TX)} {f(TY)})">'

        bx0 = BX - 392.3
        bw = 2 * 392.3
        g = GRILLE
        step = (g['y1'] - g['y0']) / (g['n'] - 1)
        slots = ''.join(
            f'<path d="M{f(CAPX - hl)},{f(g["y0"] + i * step + 1.5)} Q{CAPX},{f(g["y0"] + i * step + 1.5)} {f(CAPX + hl)},{f(g["y0"] + i * step + 1.5)}" stroke="#020203" stroke-width="4.6"/>'
        f'<path d="M{f(CAPX - hl + 2)},{f(g["y0"] + i * step + 4.4)} Q{CAPX},{f(g["y0"] + i * step + 4.4)} {f(CAPX + hl - 2)},{f(g["y0"] + i * step + 4.4)}" stroke="#4a4c50" stroke-opacity="0.8" stroke-width="1.1"/>'
            for i, hl in enumerate(g['half']))
        words = ''.join(f'<path fill="{w[6]}" d="{word_path(*w[:6], w[7])}"/>' for w in WORDS[:2])
        compaq = word_path(*WORDS[2][:6], WORDS[2][7])
        sk = 1 / S   # glyphs and button furniture are sized in units; draw them at 1/S inside the px group
        buttons = ''.join(
            f'<g transform="translate({x},{y}) scale({f(sk)})"><use href="#ip-dish-btn"/>{GLYPHS[k]}</g>'
            for x, y, k in BUTTONS)
        px, py = POWER
        ledx, ledy, ledr = WINDOW
        mx, my0, my1 = MIC

        return head + f'''<!--
  Compaq iPAQ h3900, front view. Glass: <rect id="screen"> x={f(GLASS_U[0])} y={f(GLASS_U[1])} width={GLASS_U[2]} height={GLASS_U[3]} (3:4, 240x320 px at 2.1875 units per pixel, as in the h2200 drawings).

  SPDX-FileCopyrightText: 2026 Koen Kooi
  SPDX-License-Identifier: CC-BY-SA-4.0

  Provenance: an original vector drawing, written as SVG geometry and
  gradients and drawn with the assistance of Claude (Opus 5.5) from
  photographs of the author's own iPAQ h3900. No third-party artwork was
  traced or embedded. The printed marks are glyph outlines from the Mukta and
  Open Sans fonts (SIL Open Font License). "Compaq", "iPAQ" and "Pocket PC"
  are trademarks of their owners and appear only to identify the device.
  The body width was corrected from the owner's own photographs of the
  h3900 and of the h5550.
-->
<defs>
  <linearGradient id="ip-face-h" gradientUnits="userSpaceOnUse" x1="{bx0}" y1="0" x2="{bx0 + bw}" y2="0">
    <stop offset="0" stop-color="#6c6f73"/>
    <stop offset="0.012" stop-color="#9a9da1"/>
    <stop offset="0.026" stop-color="#e9eaeb"/>
    <stop offset="0.04" stop-color="#cfd1d3"/>
    <stop offset="0.3" stop-color="#d9dbdc"/>
    <stop offset="0.62" stop-color="#d2d4d6"/>
    <stop offset="0.955" stop-color="#c3c6c8"/>
    <stop offset="0.972" stop-color="#d9dbdd"/>
    <stop offset="0.988" stop-color="#9c9fa3"/>
    <stop offset="1" stop-color="#686b6f"/>
  </linearGradient>
  <linearGradient id="ip-face-v" gradientUnits="userSpaceOnUse" x1="0" y1="70" x2="0" y2="1395">
    <stop offset="0" stop-color="#fff" stop-opacity="0.4"/>
    <stop offset="0.07" stop-color="#fff" stop-opacity="0.12"/>
    <stop offset="0.5" stop-color="#fff" stop-opacity="0"/>
    <stop offset="0.8" stop-color="#000" stop-opacity="0.04"/>
    <stop offset="1" stop-color="#000" stop-opacity="0.2"/>
  </linearGradient>
  <linearGradient id="ip-sheen" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#fff" stop-opacity="0"/>
    <stop offset="0.35" stop-color="#fff" stop-opacity="0.12"/>
    <stop offset="0.45" stop-color="#fff" stop-opacity="0"/>
    <stop offset="1" stop-color="#fff" stop-opacity="0"/>
  </linearGradient>
  <pattern id="ip-brush" width="6.857" height="3.429" patternUnits="userSpaceOnUse">
    <rect width="6.857" height="1.143" fill="#fff" fill-opacity="0.045"/>
    <rect y="2.286" width="6.857" height="0.686" fill="#000" fill-opacity="0.018"/>
  </pattern>
  <linearGradient id="ip-record" gradientUnits="userSpaceOnUse" x1="{RECORD_PTS[10][0] - 1}" y1="0" x2="{BX - 380}" y2="0">
    <stop offset="0" stop-color="#7c7f83"/><stop offset="0.12" stop-color="#b4b7ba"/>
    <stop offset="0.35" stop-color="#e2e4e5"/><stop offset="1" stop-color="#d4d6d8"/>
  </linearGradient>
  <linearGradient id="ip-cap-rim" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#8a8d91"/><stop offset="0.05" stop-color="#5a5c60"/>
    <stop offset="0.5" stop-color="#3a3c40"/><stop offset="0.95" stop-color="#55585c"/><stop offset="1" stop-color="#7b7e82"/>
  </linearGradient>
  <linearGradient id="ip-cap" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#2e3034"/><stop offset="0.25" stop-color="#16171a"/>
    <stop offset="0.75" stop-color="#0b0c0d"/><stop offset="1" stop-color="#1c1d20"/>
  </linearGradient>
  <linearGradient id="ip-bev-top" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#9da0a3"/><stop offset="1" stop-color="#6e7175"/>
  </linearGradient>
  <linearGradient id="ip-bev-bot" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#f3f4f4"/><stop offset="1" stop-color="#c6c8ca"/>
  </linearGradient>
  <linearGradient id="ip-bev-l" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#a5a8ab"/><stop offset="1" stop-color="#7c7f83"/>
  </linearGradient>
  <linearGradient id="ip-bev-r" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#eceded"/><stop offset="1" stop-color="#c3c5c7"/>
  </linearGradient>
  <linearGradient id="ip-glass" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#fff" stop-opacity="0.06"/>
    <stop offset="0.45" stop-color="#fff" stop-opacity="0.012"/>
    <stop offset="1" stop-color="#fff" stop-opacity="0"/>
  </linearGradient>
  <linearGradient id="ip-led-l" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#000" stop-opacity="0.35"/><stop offset="0.45" stop-color="#fff" stop-opacity="0.15"/><stop offset="1" stop-color="#000" stop-opacity="0.28"/>
  </linearGradient>
  <linearGradient id="ip-led-r" href="#ip-led-l" x1="1" y1="0" x2="0" y2="0"/>
  <linearGradient id="ip-led-v" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#fff" stop-opacity="0.25"/><stop offset="0.4" stop-color="#fff" stop-opacity="0"/>
    <stop offset="1" stop-color="#000" stop-opacity="0.3"/>
  </linearGradient>
  <radialGradient id="ip-led" cx="0.5" cy="0.5" r="0.5" fx="0.4" fy="0.35">
    <stop offset="0" stop-color="#f6f3e6"/><stop offset="0.6" stop-color="#cfcab6"/><stop offset="1" stop-color="#7e7a6c"/>
  </radialGradient>
  <radialGradient id="ip-dish" cx="0.5" cy="0.5" r="0.5" fx="0.6" fy="0.72">
    <stop offset="0.6" stop-color="#8d9094"/><stop offset="0.85" stop-color="#d4d6d8"/><stop offset="1" stop-color="#f3f4f5"/>
  </radialGradient>
  <linearGradient id="ip-dish-rim" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#8b8e92"/><stop offset="1" stop-color="#f8f9f9"/>
  </linearGradient>
  <radialGradient id="ip-chrome" cx="0.5" cy="0.5" r="0.5" fx="0.38" fy="0.3">
    <stop offset="0" stop-color="#ffffff"/>
    <stop offset="0.22" stop-color="#e3e4e5"/>
    <stop offset="0.55" stop-color="#a9abae"/>
    <stop offset="0.78" stop-color="#6f7174"/>
    <stop offset="0.9" stop-color="#c3c5c7"/>
    <stop offset="1" stop-color="#55575a"/>
  </radialGradient>
  <linearGradient id="ip-chrome-ring" x1="0" y1="0" x2="0.3" y2="1">
    <stop offset="0" stop-color="#f4f4f4"/><stop offset="0.3" stop-color="#8e8f92"/>
    <stop offset="0.55" stop-color="#3c3d40"/><stop offset="0.8" stop-color="#d0d1d3"/><stop offset="1" stop-color="#fff"/>
  </linearGradient>
  <linearGradient id="ip-pad" x1="0.2" y1="0" x2="0.4" y2="1">
    <stop offset="0" stop-color="#f4f5f5"/><stop offset="0.45" stop-color="#d8dadc"/>
    <stop offset="0.8" stop-color="#b3b6b9"/><stop offset="1" stop-color="#cfd1d3"/>
  </linearGradient>
  <radialGradient id="ip-pad-rim" cx="0.5" cy="0.5" r="0.5">
    <stop offset="0.75" stop-color="#000" stop-opacity="0"/>
    <stop offset="0.95" stop-color="#000" stop-opacity="0.18"/>
    <stop offset="1" stop-color="#000" stop-opacity="0.35"/>
  </radialGradient>
  <radialGradient id="ip-boss" cx="0.5" cy="0.45" r="0.5">
    <stop offset="0.55" stop-color="#fff" stop-opacity="0.32"/>
    <stop offset="1" stop-color="#fff" stop-opacity="0"/>
  </radialGradient>
  <filter id="ip-shadow" x="-10%" y="-10%" width="120%" height="125%">
    <feGaussianBlur in="SourceAlpha" stdDeviation="13.714"/>
    <feOffset dy="11.429" result="b"/>
    <feFlood flood-color="#000" flood-opacity="0.35"/>
    <feComposite in2="b" operator="in"/>
  </filter>
  <filter id="ip-soft" x="-30%" y="-30%" width="160%" height="160%">
    <feGaussianBlur stdDeviation="1.8"/>
  </filter>
  <clipPath id="ip-face-clip"><path d="{body}"/></clipPath>
  <clipPath id="ip-cap-clip"><path d="{cap_in}"/></clipPath>
  <g id="ip-dish-btn">
    <circle r="{f(DISH_R * S + 0.5)}" fill="url(#ip-dish-rim)"/>
    <circle r="{f(DISH_R * S - 2)}" fill="url(#ip-dish)"/>
    <circle r="{f(RING_R * S)}" fill="#1d1d1f"/>
    <circle r="{f(FACE_R * S)}" fill="url(#ip-chrome)"/>
    <ellipse cx="-7" cy="-11" rx="11" ry="5" fill="#fff" fill-opacity="0.5" filter="url(#ip-soft)"/>
  </g>
</defs>

{group}
<g id="shadow" fill="#000" filter="url(#ip-shadow)"><path d="{body}"/><path d="{record}"/></g>
<g id="device">
  <!-- record button housing, widening the top-left corner; the face edge over it is the seam -->
  <g id="record">
    <path d="{record}" fill="url(#ip-record)" stroke="#6c6f73" stroke-width="1.2"/>
    <path d="M{f(RECORD_PTS[10][0] + 3)},{140} L{f(RECORD_PTS[11][0] + 3)},{186}" stroke="#9a9da1" stroke-width="1.6" stroke-linecap="round"/>
  </g>
  <g id="face">
    <path id="face-base" d="{body}" fill="url(#ip-face-h)" stroke="#6c6f73" stroke-width="1.714"/>
    <g clip-path="url(#ip-face-clip)">
      <rect x="{bx0 - 20}" y="40" width="{bw + 40}" height="1380" fill="url(#ip-face-v)"/>
      <rect x="{bx0 - 20}" y="40" width="{bw + 40}" height="1380" fill="url(#ip-brush)"/>
      <rect x="{bx0 - 20}" y="40" width="{bw + 40}" height="1380" fill="url(#ip-sheen)"/>
      <!-- top-edge highlight along the shoulders, and the face turning under at the bottom -->
      <path d="{spline([(BX - 381, 98), (BX - 330, 86.6), (BX - 245, 76.5), (BX, 81), (BX + 245, 76.5), (BX + 330, 86.6), (BX + 381, 98)], closed=False)}" fill="none" stroke="#fff" stroke-opacity="0.75" stroke-width="2.3"/>
      <path d="{spline(mirror([(h, y) for h, y in BODY_HALF if y >= 1180], BX), closed=False)}" fill="none" stroke="#000" stroke-opacity="0.2" stroke-width="{2 * CHIN}"/>
      <path d="{spline(mirror([(max(h - CURL * 0.9, 0), y - CHIN) for h, y in BODY_HALF if y >= 1180], BX), closed=False)}" fill="none" stroke="#fff" stroke-opacity="0.55" stroke-width="2"/>
      <path d="M{f(BX - body_half_at(140) + CURL)},{140} C{f(BX - body_half_at(600) + CURL)},{600} {f(BX - body_half_at(1000) + CURL)},{1000} {f(BX - body_half_at(1222) + 4 + CURL)},{1230} M{f(BX + body_half_at(140) - CURL)},{140} C{f(BX + body_half_at(600) - CURL)},{600} {f(BX + body_half_at(1000) - CURL)},{1000} {f(BX + body_half_at(1222) - 4 - CURL)},{1230}" fill="none" stroke="#fff" stroke-opacity="0.45" stroke-width="2"/>
    </g>
  </g>

  <!-- black top cap: LED windows down both sides, gloss shell, grille, round window, mic, power -->
  <g id="cap">
    <path d="{cap}" fill="#141518" stroke="#0c0d0e" stroke-width="1.5"/>
    <path d="{cap_in}" fill="url(#ip-cap)"/>
    <g id="leds">
      <!-- light pipes: Bluetooth left (h3970 only), power/charge right beside the power button (HP Getting Started, page 8) -->
      <path id="led-bluetooth" aria-label="Bluetooth indicator" d="{led_l}" fill="#8e9195"/>
      <path id="led-power" aria-label="Power and charge indicator" d="{led_r}" fill="#8e9195"/>
      <g pointer-events="none">
        <path d="{led_l}" fill="url(#ip-led-l)"/><path d="{led_r}" fill="url(#ip-led-r)"/>
        <path d="{led_l}" fill="url(#ip-led-v)"/><path d="{led_r}" fill="url(#ip-led-v)"/>
        <path d="{led_hl_l}" fill="none" stroke="#fff" stroke-opacity="0.55" stroke-width="1.6" stroke-linecap="round"/>
        <path d="{led_hl_r}" fill="none" stroke="#fff" stroke-opacity="0.55" stroke-width="1.6" stroke-linecap="round"/>
      </g>
    </g>
    <g clip-path="url(#ip-cap-clip)">
      <path d="M{CAPX - 200},{58} Q{CAPX},{14} {CAPX + 200},{58}" fill="none" stroke="#fff" stroke-opacity="0.14" stroke-width="9" filter="url(#ip-soft)"/>
      <path d="M{CAPX - 230},{186} Q{CAPX},{204} {CAPX + 230},{186}" fill="none" stroke="#fff" stroke-opacity="0.07" stroke-width="10" filter="url(#ip-soft)"/>
    </g>
    <path fill="#f1f2f3" d="{compaq}"/>
    <g fill="none" stroke-linecap="round">{slots}</g>
    <path d="M{mx - 3},{my0} V{my1} M{mx + 3},{my0 + 2} V{my1 - 2}" stroke="#55575b" stroke-width="2" stroke-linecap="round"/>
    <circle cx="{ledx}" cy="{ledy}" r="{ledr + 2}" fill="#3a3c40"/>
    <circle cx="{ledx}" cy="{ledy}" r="{ledr}" fill="url(#ip-led)"/>
    <g id="power" transform="translate({px},{py}) scale({f(sk)})">
      <circle r="27" fill="url(#ip-chrome-ring)"/>
      <circle r="21.5" fill="#1d1d1f"/>
      <circle r="20" fill="url(#ip-chrome)"/>
      <ellipse cx="-6" cy="-9" rx="9" ry="4" fill="#fff" fill-opacity="0.45" filter="url(#ip-soft)"/>
      <path d="M-5.2,-6.5 A9,9 0 1 0 5.2,-6.5" fill="none" stroke="#111" stroke-width="2.8" stroke-linecap="round" transform="translate(0,2)"/>
      <line x1="0" y1="-9.5" x2="0" y2="0.5" stroke="#111" stroke-width="2.8" stroke-linecap="round"/>
    </g>
  </g>

  <!-- printed wordmarks -->
  <g id="wordmarks">{words}</g>

  <!-- recessed screen opening: mitred bevel, dark border, glass -->
  <g id="frame">
    <polygon points="{pts([(o0[0], o0[1]), (o0[2], o0[1]), (o1[2], o1[1]), (o1[0], o1[1])])}" fill="url(#ip-bev-top)"/>
    <polygon points="{pts([(o0[0], o0[3]), (o0[2], o0[3]), (o1[2], o1[3]), (o1[0], o1[3])])}" fill="url(#ip-bev-bot)"/>
    <polygon points="{pts([(o0[0], o0[1]), (o1[0], o1[1]), (o1[0], o1[3]), (o0[0], o0[3])])}" fill="url(#ip-bev-l)"/>
    <polygon points="{pts([(o0[2], o0[1]), (o1[2], o1[1]), (o1[2], o1[3]), (o0[2], o0[3])])}" fill="url(#ip-bev-r)"/>
    <rect x="{o0[0]}" y="{o0[1]}" width="{o0[2] - o0[0]}" height="{o0[3] - o0[1]}" fill="none" stroke="#7a7d81" stroke-opacity="0.6" stroke-width="1.143"/>
    <rect id="bezel" x="{o1[0]}" y="{o1[1]}" width="{o1[2] - o1[0]}" height="{o1[3] - o1[1]}" rx="1.5" fill="#131416"/>
  </g>

  <!-- navigation pad on a raised boss -->
  <g id="navpad">
    <ellipse cx="{n['cx']}" cy="{n['cy'] - 6}" rx="{n['boss'][0]}" ry="{n['boss'][1]}" fill="url(#ip-boss)"/>
    <ellipse cx="{n['cx']}" cy="{n['cy'] + 4}" rx="{n['ring'][0] + 2}" ry="{n['ring'][1] + 2}" fill="#000" fill-opacity="0.35" filter="url(#ip-soft)"/>
    <ellipse cx="{n['cx']}" cy="{n['cy']}" rx="{n['ring'][0]}" ry="{n['ring'][1]}" fill="url(#ip-chrome-ring)" stroke="#2a2b2d" stroke-width="1.5"/>
    <ellipse cx="{n['cx']}" cy="{n['cy']}" rx="{n['gap'][0]}" ry="{n['gap'][1]}" fill="#1a1b1d"/>
    <ellipse cx="{n['cx']}" cy="{n['cy']}" rx="{n['pad'][0]}" ry="{n['pad'][1]}" fill="url(#ip-pad)"/>
    <ellipse cx="{n['cx']}" cy="{n['cy']}" rx="{n['pad'][0]}" ry="{n['pad'][1]}" fill="url(#ip-pad-rim)"/>
    <path d="M{n['cx'] - 150},{n['cy'] - 42} Q{n['cx'] - 60},{n['cy'] - 82} {n['cx'] + 60},{n['cy'] - 76}" fill="none" stroke="#fff" stroke-opacity="0.75" stroke-width="3" filter="url(#ip-soft)"/>
    <g fill="#55585c">
      <path d="{lens(n['cx'] - 108, n['cy'] + 2, n['cx'] - 16, n['cy'] + 2, 3)}"/>
      <path d="{lens(n['cx'] + 16, n['cy'] + 2, n['cx'] + 108, n['cy'] + 2, 3)}"/>
      <path d="{lens(n['cx'], n['cy'] - 40, n['cx'], n['cy'] - 10, 3.4)}"/>
      <path d="{lens(n['cx'], n['cy'] + 12, n['cx'], n['cy'] + 48, 3.4)}"/>
    </g>
  </g>

  <!-- application buttons -->
  <g id="app-buttons">{buttons}</g>
</g>
</g>

<!-- glass slot in SVG units: a neutral placeholder until a screenshot is composited -->
<rect id="screen" x="{f(GLASS_U[0])}" y="{f(GLASS_U[1])}" width="{GLASS_U[2]}" height="{GLASS_U[3]}" fill="#c3c6c9"/>
<rect id="glass" x="{f(GLASS_U[0])}" y="{f(GLASS_U[1])}" width="{GLASS_U[2]}" height="{GLASS_U[3]}" fill="url(#ip-glass)" pointer-events="none"/>
</svg>
'''

    return build()


def build_h5550(fonts):
    """Draw the h5550 from measured photo coordinates."""
    S = 0.875
    VB_X, VB_Y = -0.3125, -0.25            # the h3900 drawing's canvas
    CSS_W, CSS_H = 366, 602            # the h3900 canvas, 17 CSS px taller for the lower body
    VB_W, VB_H = CSS_W * 2.1875, CSS_H * 2.1875
    GLASS_U = (137.5, 244.75, 525, 700)
    GX, GY, GW, GH = 275, 262, 600, 800
    TX = GLASS_U[0] - GX * S
    TY = GLASS_U[1] - GY * S
    CX = 575

    # The shared h3900 envelope, from y >= 94 in photo coordinates.
    BX = 591
    ENV = IPAQ_BODY_HALF[8:]
    ENV_STROKE = 1.7 / S       # the h3900 outline stroke, 1.7 units
    K_BODY = 776.6 / 842.5     # envelope width / photo width at mid-height


    def env_half(yd):
        """envelope half-width at drawing height yd (constant 392.3 above the corner)"""
        if yd <= 125:
            return 392.3
        for (h0, y0), (h1, y1) in zip(ENV[3:], ENV[4:]):
            if y0 <= yd <= y1:
                return h0 + (h1 - h0) * (yd - y0) / (y1 - y0)
        return 0.0


    # ---- photo -> drawing mapping ---------------------------------------------------
    Y_TOP, Y_BANDT, Y_BANDB, Y_BOT = 63.5, 245, 1073.6, 1450.3   # photo: cap top, band top/bottom, body bottom
    H3900_LEN = 1389.6 - 22    # the h3900 drawing's length, cap top to bottom
    # Outside the band the photo is scaled by one factor K_OUT, above and below alike (the photo's
    # proportions), so that the h5550 is 10 gp (1 mm, HP 133 vs 134 mm) shorter than the h3900 file;
    # the envelope moves down by ENV_DY so its bottom meets the photo's.
    K_OUT = (H3900_LEN - 10 - (Y_BANDB - Y_BANDT)) / ((Y_BANDT - Y_TOP) + (Y_BOT - Y_BANDB))
    ENV_DY = Y_BANDB + (Y_BOT - Y_BANDB) * K_OUT - 1389.6
    K_PAD = 1.0                # round parts keep the photo's size
    BAND_L, BAND_R = 261, 889.5


    def my(y):
        if y <= Y_BANDT:
            return Y_BANDT - (Y_BANDT - y) * K_OUT
        if y <= Y_BANDB:
            return y
        return Y_BANDB + (y - Y_BANDB) * K_OUT


    # photo side lines (outer edge, threshold 45, tools/outline2.py), without the bulge
    PHOTO_L = [(150, 160.5), (400, 160.8), (450, 162.3), (500, 162.3), (600, 161.6), (700, 163.5), (800, 164.2),
               (900, 165.8), (1000, 167.4), (1100, 168.3), (1150, 169.5), (1200, 171), (1250, 171.8)]
    PHOTO_R = [(150, 1008.3), (200, 1008.5), (250, 1007.5), (300, 1007), (400, 1006.5), (500, 1005.2), (600, 1004),
               (700, 1003.2), (800, 1002), (900, 1000.6), (1000, 998.6), (1100, 996.6), (1150, 994.3),
               (1200, 992.3), (1250, 991.6)]


    def interp(table, y):
        if y <= table[0][0]:
            return table[0][1]
        for (y0, v0), (y1, v1) in zip(table, table[1:]):
            if y0 <= y <= y1:
                return v0 + (v1 - v0) * (y - y0) / (y1 - y0)
        return table[-1][1]


    def mxl(x, y):
        pp, ed = interp(PHOTO_L, y), BX - env_half(my(y) - ENV_DY)
        if x >= BAND_L:
            return x
        if x >= pp:
            return BAND_L - (BAND_L - x) * (BAND_L - ed) / (BAND_L - pp)
        return ed - (pp - x) * K_BODY


    def mxr(x, y):
        pp, ed = interp(PHOTO_R, y), BX + env_half(my(y) - ENV_DY)
        if x <= BAND_R:
            return x
        if x <= pp:
            return BAND_R + (x - BAND_R) * (ed - BAND_R) / (pp - BAND_R)
        return ed + (x - pp) * K_BODY


    def M(pts):
        """map photo points (x by side, y by height)"""
        return [((mxl(x, y) if x < CX else mxr(x, y)), my(y)) for x, y in pts]


    # ---- photo measurements (gp, photo) ------------------------------------------------
    TOP_C = [(0, 63.5), (45, 64.0), (75, 64.6), (105, 66.2), (135, 68.4), (165, 71.6), (195, 75.4),
             (220, 78.0), (250, 82.7), (280, 88.3)]
    TOP_L = [(0, 63.5), (45, 64.0), (75, 64.6), (105, 66.2), (135, 68.4), (165, 71.6), (195, 77.0),
             (220, 80.5)]
    # right shoulder rim top, with the stylus head (x 932-958)
    SHOULDER_R = [(870, 93), (900, 100), (922, 101), (932, 97.5), (948, 97), (958, 103), (966, 108.5),
                  (978, 116), (992, 124.5), (999.5, 130), (1004, 136), (1006.5, 143)]
    BULGE = [(128.5, 175), (126.4, 190), (125.4, 205), (127.5, 225), (131, 245), (135.5, 265),
             (141, 285), (146.5, 305), (151.5, 327), (156, 350), (158.8, 370), (160.4, 388)]
    LEFT_CORNER = [(200, 121), (180, 131.6), (150, 147.5), (133, 162)]
    # Antenna stub (photo outline); drawn rigid at K_BODY, anchored at its base on the left shoulder
    ANT = [(200, 121), (210, 110), (216, 100), (222, 80), (229, 62), (236, 47), (246, 35), (260, 26),
           (280, 21), (300, 19), (320, 18.5), (338, 21), (352, 28), (362, 40), (369, 56), (373, 72), (376, 84)]
    ANT_BASE = (214, 121)


    def ant_map(x, y):
        bx, by = mxl(ANT_BASE[0], ANT_BASE[1]), my(ANT_BASE[1])
        return (bx + (x - ANT_BASE[0]) * K_BODY, by + (y - ANT_BASE[1]) * K_BODY)


    # Black top piece (centred on 575, photo)
    CAP_SIDE = [(299, 118), (298.5, 130), (296, 146), (293.5, 162), (289.5, 178), (284, 190),
                (276, 198), (262, 204), (245, 207.2), (225, 209.5), (195, 212.3), (160, 214.6),
                (120, 216.2), (60, 217.3), (0, 217.6)]
    RIM_LOW_R = [(1006.8, 146), (1002, 138.5), (994, 133.5), (980, 131), (960, 128), (930, 122.5),
                 (900, 119), (880, 116)]
    RIM_LOW_L = [(272, 118.5), (250, 120.5), (230, 123), (212, 126), (200, 129), (188, 135), (178, 142)]

    PLATE = dict(cx=579, cy=111.5, w=92.5, h=60, r=4.5)
    HP_R = 25
    LEDS = [(337.5, 115, 11.5, 4.8), (342.5, 147, 12, 5.6), (345.5, 180.5, 12, 5.2)]
    GRILLE = dict(x0=463, x1=704, ridges=(154, 171.5, 189), slots=(148.5, 165, 182, 198))
    POWER = dict(cx=805, cy=145, r=39.5, dome=26.5, collar=(807, 147.5, 47.5))
    # Lit amber in a charging photo, so the power indicator (QuickSpecs item 2), not a light sensor.
    SENSOR_ALS = (748, 172.5, 10.5)

    BAND = (261, 245, 889.5, 1073.6)      # outer edge of the dark band round the glass

    # below the band (photo; positions go through my(), sizes through K_PAD)
    BUTTONS = [(CX - 195, 1180, 'contacts'), (CX - 226.5, 1288, 'calendar'),
               (CX + 195, 1180, 'mail'), (CX + 226.5, 1288, 'task')]
    BTN_R = 34.5
    DISH = dict(rx=54.5, ry=46.5, dx=17, dy=1)
    NAV = dict(cx=575, cy=1210)
    VALLEY = [(117, 1446), (128, 1425), (140, 1400), (158, 1375), (165, 1350), (160.5, 1320),
              (154.5, 1290), (148.5, 1260), (135, 1230), (121.5, 1200), (99, 1170), (72, 1141),
              (40, 1126), (0, 1121)]
    GROOVE = dict(top=1240, x_top=(509, 642), x_bot=(505, 645.5), bot=1450)
    SENSOR = (1339.5, 1357)
    MIC = [(411, 1364.5, 7, 3.2), (411.5, 1375.5, 15.5, 4.2), (412, 1386.5, 7.5, 3.2)]
    PAD_T = f'matrix(1 0 0 {K_OUT:.5f} 0 {Y_BANDB * (1 - K_OUT):.3f})'   # photo -> drawing below the band
    CAP_T = f'matrix(1 0 0 {K_OUT:.5f} 0 {Y_BANDT * (1 - K_OUT):.3f})'   # photo -> drawing above the band


    WORDS = [
        ('iPAQ', 'Roboto_Bold.ttf', 23.4 * K_PAD, 287.5, my(1119.3), 'start', '#3a362f', 66.5 * K_PAD),
        ('Pocket PC', 'Roboto_Regular.ttf', 22.3 * K_PAD, 866, my(1120.8), 'end', '#5a5446', 140.5 * K_PAD),
    ]








    word_path = fonts.word_path


    def ant_pts():
        return [ant_map(x, y) for x, y in ANT]


    def ant_right():
        return max(x for x, _ in ant_pts())


    def top_left():
        """cap top edge left of the centre, right of the antenna (drawing)"""
        return [(CX - h, my(y)) for h, y in TOP_L if CX - h > ant_pts()[-2][0] + 3]


    def top_right():
        return [(CX + h, my(y)) for h, y in TOP_C] + M(SHOULDER_R)


    def env_right():
        """right envelope side; extra samples below the corner keep the spline from overshooting"""
        extra = [(BX + env_half(y), y + ENV_DY) for y in (122, 135, 160, 200, 250)]
        return extra + [(BX + h, y + ENV_DY) for h, y in ENV if y >= 300 and h > 0]


    def env_left():
        """left envelope side from the bottom up to y 400 (the bulge takes over above)"""
        return [(BX - h, y + ENV_DY) for h, y in reversed(ENV) if y >= 400 and h > 0]


    def body_points():
        right = top_right() + env_right()
        left = env_left() + list(reversed(M(BULGE))) + list(reversed(M(LEFT_CORNER)))
        return right + [(BX, ENV[-1][1] + ENV_DY)] + left + ant_pts()[2:-1] + list(reversed(top_left()))[:-1]


    def cap_points():
        """black top piece: top edge, right shoulder rim, cap, left shoulder rim (drawing)"""
        top = list(reversed(top_left())) + top_right()[1:]
        cap_r = [(CX + h, my(y)) for h, y in CAP_SIDE]
        cap_l = [(CX - h, my(y)) for h, y in reversed(CAP_SIDE[:-1])]
        corner = list(reversed(M(LEFT_CORNER)))
        a2 = ant_pts()[2]
        return top + M(RIM_LOW_R) + cap_r + cap_l + M(RIM_LOW_L) + corner + \
            [a2, (a2[0] + 36, my(97)), (300, my(94))]


    def offset(points, d):
        """offset a polyline by d along its left normal (positive = outwards for the valley's right half order)"""
        out = []
        n = len(points)
        for i, (x, y) in enumerate(points):
            x0, y0 = points[max(i - 1, 0)]
            x1, y1 = points[min(i + 1, n - 1)]
            tx, ty = x1 - x0, y1 - y0
            L = (tx * tx + ty * ty) ** 0.5 or 1
            out.append((x - ty / L * d, y + tx / L * d))
        return out


    def valley_line(d=0, cut=0):
        pts = [(CX + h, y) for h, y in VALLEY] + [(CX - h, y) for h, y in reversed(VALLEY) if h != 0]
        pts = offset(pts, d)
        if cut:
            pts = pts[cut:-cut]
        return spline(pts, closed=False, tension=6.0)


    def hp_letters():
        """white h and p in unskewed plate-local units (origin plate centre); skewX applied by caller"""
        # h: stem u -17.3..-9.8 from the plate top to the baseline 12.5; arch to the leg u -8.6..-0.9
        h = ('M-18,-31 H-10 V-11.8 C-8.2,-12.8 -6.4,-13.2 -4.6,-13.2 C-1.6,-13.2 0.2,-11.2 0.2,-7.8 V12.5 H-8.2 '
         'V-4.4 C-8.2,-5.8 -8.8,-6.4 -10,-6.4 V12.5 H-18 Z')
        # p: stem u 0.8..8.4 from the x-height to the plate bottom; bowl to u 20.5; counter u 10..14.6
        p = ('M1.4,-11.8 C3,-12.8 5.2,-13.2 7.6,-13.2 H13.4 C20.4,-13.2 23.6,-9 23.6,-0.3 C23.6,8.6 20.4,12.5 13.4,12.5 '
         'H9.6 V31 H1.4 Z M9.6,-6.2 V6.4 H10.6 C11.8,6.4 12.4,3.8 12.4,0 C12.4,-3.8 11.8,-6.2 10.6,-6.2 Z')
        return h + ' ' + p


    GLYPHS = {
        'calendar': '''<g fill="#1e1f21" fill-opacity="0.6" transform="translate(-9,-9)">
        <rect width="18" height="4" rx="1"/>
        <rect y="5.5" width="4.2" height="3.4"/><rect x="4.6" y="5.5" width="4.2" height="3.4"/><rect x="9.2" y="5.5" width="4.2" height="3.4"/><rect x="13.8" y="5.5" width="4.2" height="3.4"/>
        <rect y="9.8" width="4.2" height="3.4"/><rect x="4.6" y="9.8" width="4.2" height="3.4"/><rect x="9.2" y="9.8" width="4.2" height="3.4"/><rect x="13.8" y="9.8" width="4.2" height="3.4"/>
        <rect y="14.1" width="4.2" height="3.4"/><rect x="4.6" y="14.1" width="4.2" height="3.4"/><rect x="9.2" y="14.1" width="4.2" height="3.4"/>
      </g>''',
        'contacts': '''<g transform="translate(-10,-9)" fill="none" stroke="#1e1f21" stroke-opacity="0.6" stroke-width="1.6">
        <rect width="20" height="18" rx="1.5"/>
        <circle cx="6" cy="6.5" r="2.4"/><path d="M2.5,14.5 Q2.5,10 6,10 Q9.5,10 9.5,14.5"/>
        <path d="M12.5,5 H17.5 M12.5,9 H17.5 M12.5,13 H17.5"/>
      </g>''',
        'mail': '''<g transform="translate(-10.5,-7.5)" fill="none" stroke="#1e1f21" stroke-opacity="0.6" stroke-width="1.8" stroke-linejoin="round">
        <rect width="21" height="15" rx="1"/>
        <path d="M0,0 L10.5,8.5 L21,0 M0,15 L8,7 M21,15 L13,7"/>
      </g>''',
        'task': '''<g fill="none" stroke="#1e1f21" stroke-opacity="0.6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M-7,6 A8.5,8.5 0 1 1 6.5,-6.5"/>
        <path d="M1.5,-9.5 L7,-6.6 L4.4,-0.8"/>
      </g>''',
    }


    # face colour across the body at mid-height, sampled on the rectified photo (rows 662 and 900, 9x9 px means),
    # The samples move with the outline's horizontal mapping.
    FACE_STOPS_P = [(154, '#3a362f'), (160, '#141210'), (167, '#0e0d0b'), (172, '#26231e'), (180, '#3b362e'),
                  (188, '#4f483d'), (196, '#675e50'), (204, '#837867'), (212, '#a99c88'), (220, '#cbbca5'),
                  (228, '#e2d3b9'), (240, '#eedfc3'), (256, '#f5e6ca'), (420, '#f8e7c9'), (1000, '#f9e8c8')]
    # right side: drawn as an overlay that fades in from the plateau (colour, opacity)
    FACE_R_STOPS_P = [(872, '#fcf2cc', 0), (902, '#fcf2cc', 1), (922, '#fdf7d3', 1), (940, '#fefbe2', 1), (952, '#fbf6db', 1),
                    (960, '#ebdcc1', 1), (964, '#d6c6ac', 1), (968, '#bbad96', 1), (972, '#9a8e7c', 1), (976, '#71685b', 1),
                    (980, '#544d43', 1), (984, '#3e3932', 1), (988, '#2b2722', 1), (993, '#1d1a17', 1), (998, '#2f2b26', 1)]
    FACE_STOPS = [(mxl(x + 8, 662), c) for x, c in FACE_STOPS_P]
    FACE_R_STOPS = [(mxr(x + 8, 662), c, o) for x, c, o in FACE_R_STOPS_P]
    SKEW_R = 0.005     # right side: the photo's shading moves in only 5 gp from y 160 to 1000
    SKEW = 0.0117      # the shading follows the envelope's sides, which close in by 0.0117 gp per gp downwards


    def bulge_wall():
        outer = [(x - 6, y) for x, y in M(LEFT_CORNER[2:] + BULGE)]
        inner = [(214, my(388)), (213, my(330)), (213, my(250)), (214, my(175)), (214, my(150))]
        return spline(outer + [(206, my(410))] + inner, tension=6.0)


    def bulge_band():
        pts = M(BULGE)
        pts = M(LEFT_CORNER[3:]) + pts
        return spline([(x + 6.5 - 2 * min(1.0, max(0.0, (y - 220) / 80)) - 2 * min(1.0, max(0.0, (y - 300) / 88)), y) for x, y in pts], closed=False)


    # Owner (2026-11-08): the face is silver-grey like the device and the other frames; the photo's
    # cream is the lamp's colour. Every colour sampled from the photo is turned into a neutral grey of
    # the same luminance, light greys scaled down to sit with the h3900 drawing's face (#d2d4d6-#d9dbdc),
    # so the light direction and the contrast of the ridge, valley and groove stay the photo's.
    KEEP = {'#3a2420', '#a8706a', '#c3c6c9', '#ffffff', '#000000'}   # LED red, glass placeholder, white, black


    def silver(hexc):
        if hexc.lower() in KEEP:
            return hexc
        r, g, b = (int(hexc[i:i + 2], 16) for i in (1, 3, 5))
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        lum *= 1 - 0.065 * min(1.0, max(0.0, (lum - 90) / 110))
        return '#%02x%02x%02x' % tuple(int(max(0, min(255, round(lum + d)))) for d in (-2, 0, 1.5))


    def neutral(svg):
        import re
        return re.sub(r'#[0-9a-fA-F]{6}\b', lambda m: silver(m.group(0)), svg)


    def grad_stops(stops, x0, x1):
        return ''.join(f'<stop offset="{(s[0] - x0) / (x1 - x0):.4f}" stop-color="{s[1]}"' +
                       (f' stop-opacity="{s[2]}"' if len(s) > 2 else '') + '/>' for s in stops)


    def build():
        body = spline(body_points(), tension=6.0)   # as the h3900 file
        cap = spline(cap_points(), tension=7.0)
        ant = spline(ant_pts()[2:] + [ant_map(378, 80), ant_map(300, 97), ant_map(218, 104)], tension=6.0)
        valley = spline([(CX + h, y) for h, y in VALLEY] + [(CX - h, y) for h, y in reversed(VALLEY) if h != 0],
                        closed=False, tension=6.0)
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{CSS_W}" height="{CSS_H}" '
            f'viewBox="{VB_X!r} {VB_Y!r} {VB_W!r} {VB_H!r}">\n')
        group = f'<g transform="matrix({S} 0 0 {S} {f(TX)} {f(TY)})">'
        n = NAV
        groove = ('M513,1240 C510,1300 508.5,1360 506,1437 Q575,1441 644,1437 C641.5,1360 640,1300 636,1240 Z')
        wall_l = 'M511,1250 C504,1300 500.5,1370 501.5,1414 C502,1426 509.5,1426 510,1414 C510.5,1370 511.5,1310 515,1250 Z'
        wall_r = 'M635,1250 C638.5,1310 640,1370 640.5,1414 C641,1426 648.5,1426 649,1414 C649.5,1370 646.5,1300 639,1250 Z'
        bot_edge = spline([(BX + h, y + ENV_DY) for h, y in ENV if y >= 1100] + [(BX - h, y + ENV_DY) for h, y in reversed(ENV) if y >= 1100 and h > 0],
                          closed=False)

        words = ''.join(f'<path fill="{w[6]}" d="{word_path(*w[:6], w[7])}"/>' for w in WORDS)
        dishes = ''.join(
            f'<g transform="translate({f(x + K_PAD * (-DISH["dx"] if x < CX else DISH["dx"]))},{f(my(y + DISH["dy"]))}) scale({K_PAD})">'
        f'<ellipse rx="{DISH["rx"]}" ry="{DISH["ry"]}" fill="url(#ip-dish{"-r" if x > CX else ""})"/>'
        f'<ellipse rx="{DISH["rx"] - 1}" ry="{DISH["ry"] - 1}" fill="none" stroke="url(#ip-dish-rim{"-r" if x > CX else ""})" stroke-width="9" filter="url(#ip-blur4)"/>'
        f'</g>'
            for x, y, _ in BUTTONS)
        buttons = ''.join(
            f'<g transform="translate({f(x)},{f(my(y))}) scale({K_PAD})"><use href="#ip-btn"/><g clip-path="url(#ip-btn-clip)" opacity="0.9"><g transform="translate(-2,0) scale(1.55)">{GLYPHS[k]}</g></g><use href="#ip-btn-hi"/></g>'
            for x, y, k in BUTTONS)
        p = PLATE
        gr = GRILLE
        slots = ''.join(
            f'<path d="M{gr["x0"] + (6 if i == 0 else 0)},{y} H{gr["x1"] - (6 if i == 0 else 0)}" stroke="#030304" stroke-width="5" stroke-linecap="round"/>'
            for i, y in enumerate(gr['slots']))
        ridges = ''.join(
            f'<path d="M{gr["x0"] + 2},{y} H{gr["x1"] - 2}" stroke="url(#ip-grille-ridge)" stroke-width="1.6" stroke-linecap="round"/>'
            for y in gr['ridges'])
        # Callout order (light sensor, Bluetooth, WLAN); unlit in every photo found, so the top-to-bottom order is unverified.
        windows = ('id="light-sensor" aria-label="Light sensor"',
                   'id="led-bluetooth" aria-label="Bluetooth indicator"',
                   'id="led-wlan" aria-label="Wireless LAN indicator"')
        leds = ''.join(
            f'<ellipse {w} cx="{x}" cy="{y}" rx="{rx}" ry="{ry}" fill="#2a2b2d"/>'
            for w, (x, y, rx, ry) in zip(windows, LEDS)) + '<g pointer-events="none">' + ''.join(
            f'<ellipse cx="{x}" cy="{y - 0.6}" rx="{rx - 2.5}" ry="{ry - 2}" fill="#fff" fill-opacity="0.22" filter="url(#ip-soft)"/>'
            for x, y, rx, ry in LEDS) + '</g>'
        pw = POWER
        pcx, pcy = pw['cx'], pw['cy']
        cx_, cy_, cr_ = pw['collar']
        ax, ay, ar = SENSOR_ALS
        mic = ''.join(
            f'<ellipse cx="{x}" cy="{y + 1}" rx="{rx}" ry="{ry}" fill="#fff8e8" fill-opacity="0.55"/>'
        f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="{ry}" fill="#2a2620"/>'
            for x, y, rx, ry in MIC)
        b0 = BAND

        out = head + f'''<!--
  HP iPAQ h5550, front view. Glass: <rect id="screen"> x={f(GLASS_U[0])} y={f(GLASS_U[1])} width={GLASS_U[2]} height={GLASS_U[3]} (3:4, 240x320 px at 2.1875 units per pixel, as in the h2200 and h3900 drawings).

  SPDX-FileCopyrightText: 2026 Koen Kooi
  SPDX-License-Identifier: CC-BY-SA-4.0

  Provenance: an original vector drawing, written as SVG geometry and
  gradients and drawn with the assistance of Claude (Opus 5.5) from
  photographs of the author's own iPAQ h5550. No third-party artwork was
  traced or embedded. The body outline is the author's h3900 drawing's,
  because both devices have the same body and take the same expansion
  sleeves. The printed marks are glyph outlines from the Roboto
  font (Apache License 2.0). "HP", "iPAQ" and "Pocket PC" are trademarks of
  their owners and appear only to identify the device.
-->
<defs>
  <linearGradient id="ip-face-h" gradientUnits="userSpaceOnUse" x1="{f(FACE_STOPS[0][0])}" y1="0" x2="{f(FACE_STOPS[-1][0])}" y2="0" gradientTransform="matrix(1 0 {SKEW} 1 {f(-SKEW * 662)} 0)">
    {grad_stops(FACE_STOPS, FACE_STOPS[0][0], FACE_STOPS[-1][0])}
  </linearGradient>
  <linearGradient id="ip-face-r" gradientUnits="userSpaceOnUse" x1="{f(FACE_R_STOPS[0][0])}" y1="0" x2="{f(FACE_R_STOPS[-1][0])}" y2="0" gradientTransform="matrix(1 0 {-SKEW_R} 1 {f(SKEW_R * 662)} 0)">
    {grad_stops(FACE_R_STOPS, FACE_R_STOPS[0][0], FACE_R_STOPS[-1][0])}
  </linearGradient>
  <linearGradient id="ip-face-v" gradientUnits="userSpaceOnUse" x1="0" y1="100" x2="0" y2="1451">
    <stop offset="0" stop-color="#fffaf0" stop-opacity="0.10"/>
    <stop offset="0.1" stop-color="#fffaf0" stop-opacity="0"/>
    <stop offset="0.82" stop-color="#5a4a32" stop-opacity="0"/>
    <stop offset="0.9" stop-color="#5a4a32" stop-opacity="0.06"/>
    <stop offset="1" stop-color="#5a4a32" stop-opacity="0.12"/>
  </linearGradient>
  <linearGradient id="ip-bot-edge" gradientUnits="userSpaceOnUse" x1="170" y1="0" x2="990" y2="0">
    <stop offset="0" stop-color="#1a1611" stop-opacity="0.38"/>
    <stop offset="0.3" stop-color="#1a1611" stop-opacity="0.22"/>
    <stop offset="0.55" stop-color="#1a1611" stop-opacity="0.12"/>
    <stop offset="1" stop-color="#1a1611" stop-opacity="0.12"/>
  </linearGradient>
  <linearGradient id="ip-cap" gradientUnits="userSpaceOnUse" x1="0" y1="63" x2="0" y2="218">
    <stop offset="0" stop-color="#24221f"/><stop offset="0.15" stop-color="#0f0e0d"/>
    <stop offset="0.8" stop-color="#0b0b0a"/><stop offset="1" stop-color="#151413"/>
  </linearGradient>
  <linearGradient id="ip-cap-refl" gradientUnits="userSpaceOnUse" x1="610" y1="0" x2="880" y2="0">
    <stop offset="0" stop-color="#f3e6cf" stop-opacity="0"/>
    <stop offset="0.25" stop-color="#f3e6cf" stop-opacity="0.4"/>
    <stop offset="0.5" stop-color="#f3e6cf" stop-opacity="0.62"/>
    <stop offset="0.8" stop-color="#f3e6cf" stop-opacity="0.7"/>
    <stop offset="1" stop-color="#f3e6cf" stop-opacity="0.35"/>
  </linearGradient>
  <linearGradient id="ip-ant" gradientUnits="userSpaceOnUse" x1="{f(ant_map(214, 0)[0])}" y1="0" x2="{f(ant_map(376, 0)[0])}" y2="0">
    <stop offset="0" stop-color="#171513"/><stop offset="0.14" stop-color="#2b2824"/>
    <stop offset="0.5" stop-color="#36322d"/><stop offset="0.86" stop-color="#2a2723"/><stop offset="1" stop-color="#121110"/>
  </linearGradient>
  <linearGradient id="ip-ant-top" gradientUnits="userSpaceOnUse" x1="0" y1="{f(ant_map(0, 18)[1])}" x2="0" y2="{f(ant_map(0, 50)[1])}">
    <stop offset="0" stop-color="#0c0c0d" stop-opacity="0.9"/><stop offset="1" stop-color="#0c0c0d" stop-opacity="0"/>
  </linearGradient>
  <linearGradient id="ip-plate" x1="0" y1="0" x2="0.25" y2="1">
    <stop offset="0" stop-color="#f3ecdf"/><stop offset="0.5" stop-color="#e6dfd2"/><stop offset="1" stop-color="#d2cbbf"/>
  </linearGradient>
  <linearGradient id="ip-grille-ridge" gradientUnits="userSpaceOnUse" x1="{GRILLE['x0']}" y1="0" x2="{GRILLE['x1']}" y2="0">
    <stop offset="0" stop-color="#9a9894" stop-opacity="0.55"/><stop offset="0.5" stop-color="#7d7b77" stop-opacity="0.4"/>
    <stop offset="1" stop-color="#9a9894" stop-opacity="0.55"/>
  </linearGradient>
  <!-- power button: chrome collar (a mirror: hard bright arc right, dark reflections lower left) -->
  <linearGradient id="ip-pw-collar" x1="0.3" y1="0" x2="0.6" y2="1">
    <stop offset="0" stop-color="#6b665d"/><stop offset="0.12" stop-color="#d8d1c3"/>
    <stop offset="0.3" stop-color="#f6efe1"/><stop offset="0.7" stop-color="#f2ebdc"/>
    <stop offset="1" stop-color="#fbf5ea"/>
  </linearGradient>
  <radialGradient id="ip-pw-dome" cx="0.5" cy="0.5" r="0.5" fx="0.6" fy="0.42">
    <stop offset="0" stop-color="#3b3a38"/><stop offset="0.55" stop-color="#1c1b1a"/>
    <stop offset="0.85" stop-color="#0b0b0b"/><stop offset="1" stop-color="#2a2927"/>
  </radialGradient>
  <linearGradient id="ip-band-lip" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#8d8f91"/><stop offset="1" stop-color="#9c9ea0"/>
  </linearGradient>
  <linearGradient id="ip-glass" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#fff" stop-opacity="0.06"/>
    <stop offset="0.45" stop-color="#fff" stop-opacity="0.012"/>
    <stop offset="1" stop-color="#fff" stop-opacity="0"/>
  </linearGradient>
  <radialGradient id="ip-dish" cx="0.5" cy="0.5" r="0.5" fx="0.4" fy="0.35">
    <stop offset="0" stop-color="#fffbf0" stop-opacity="0.35"/>
    <stop offset="0.8" stop-color="#fffbf0" stop-opacity="0.2"/>
    <stop offset="0.93" stop-color="#3a2e1e" stop-opacity="0.05"/>
    <stop offset="1" stop-color="#3a2e1e" stop-opacity="0"/>
  </radialGradient>
  <linearGradient id="ip-dish-r" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#fffbf0" stop-opacity="0.3"/><stop offset="0.45" stop-color="#fffbf0" stop-opacity="0.1"/>
    <stop offset="0.75" stop-color="#3a2e1e" stop-opacity="0.22"/><stop offset="1" stop-color="#3a2e1e" stop-opacity="0.28"/>
  </linearGradient>
  <linearGradient id="ip-dish-rim" x1="0.4" y1="1" x2="0.6" y2="0">
    <stop offset="0" stop-color="#fffbf0" stop-opacity="0.5"/>
    <stop offset="0.45" stop-color="#fffbf0" stop-opacity="0.2"/>
    <stop offset="0.7" stop-color="#3a2e1e" stop-opacity="0.15"/>
    <stop offset="1" stop-color="#3a2e1e" stop-opacity="0.6"/>
  </linearGradient>
  <linearGradient id="ip-dish-rim-r" x1="0.1" y1="0.3" x2="0.9" y2="0.7">
    <stop offset="0" stop-color="#fffbf0" stop-opacity="0.3"/>
    <stop offset="0.45" stop-color="#fffbf0" stop-opacity="0"/>
    <stop offset="0.7" stop-color="#3a2e1e" stop-opacity="0.3"/>
    <stop offset="1" stop-color="#3a2e1e" stop-opacity="0.6"/>
  </linearGradient>
  <!-- app buttons: domed mirrors in a black ring -->
  <radialGradient id="ip-btn-dome" cx="0.5" cy="0.5" r="0.5" fx="0.45" fy="0.4">
    <stop offset="0" stop-color="#7d796e"/><stop offset="0.5" stop-color="#5a564d"/>
    <stop offset="0.8" stop-color="#36332e"/><stop offset="0.93" stop-color="#211f1c"/><stop offset="1" stop-color="#4a463f"/>
  </radialGradient>
  <linearGradient id="ip-btn-rim" x1="0.15" y1="0" x2="0.85" y2="1">
    <stop offset="0" stop-color="#6d6a64"/><stop offset="0.4" stop-color="#d6d0c4"/>
    <stop offset="0.65" stop-color="#3e3c38"/><stop offset="1" stop-color="#b9b3a7"/>
  </linearGradient>
  <!-- navigation button: collar rings and a curved chrome mirror -->
  <linearGradient id="ip-nav-ring" x1="0.2" y1="0" x2="0.8" y2="1">
    <stop offset="0" stop-color="#b2aa98"/><stop offset="0.45" stop-color="#ddd3bd"/>
    <stop offset="0.75" stop-color="#b8ae9a"/><stop offset="1" stop-color="#d9cfb9"/>
  </linearGradient>
  <linearGradient id="ip-nav-chrome" x1="0.15" y1="0.1" x2="0.85" y2="0.9">
    <stop offset="0" stop-color="#e9e4da"/><stop offset="0.3" stop-color="#ffffff"/>
    <stop offset="0.55" stop-color="#8d887f"/><stop offset="0.8" stop-color="#f4f0e8"/><stop offset="1" stop-color="#bdb7ab"/>
  </linearGradient>
  <radialGradient id="ip-nav-disc" cx="0.5" cy="0.5" r="0.5" fx="0.5" fy="0.45">
    <stop offset="0" stop-color="#655f56"/><stop offset="0.6" stop-color="#4f4a42"/>
    <stop offset="0.9" stop-color="#3e3a34"/><stop offset="1" stop-color="#625c52"/>
  </radialGradient>
  <linearGradient id="ip-valley" gradientUnits="userSpaceOnUse" x1="400" y1="0" x2="750" y2="0">
    <stop offset="0" stop-color="#2a2014" stop-opacity="0.9"/><stop offset="0.5" stop-color="#2a2014" stop-opacity="0.6"/>
    <stop offset="1" stop-color="#2a2014" stop-opacity="0.45"/>
  </linearGradient>
  <linearGradient id="ip-groove" gradientUnits="userSpaceOnUse" x1="0" y1="{GROOVE['top']}" x2="0" y2="{GROOVE['bot']}">
    <stop offset="0" stop-color="#2a2014" stop-opacity="0.22"/>
    <stop offset="0.25" stop-color="#2a2014" stop-opacity="0.22"/>
    <stop offset="0.48" stop-color="#2a2014" stop-opacity="0.3"/>
    <stop offset="0.49" stop-color="#2a2014" stop-opacity="0"/>
    <stop offset="1" stop-color="#2a2014" stop-opacity="0"/>
  </linearGradient>
  <filter id="ip-shadow" x="-10%" y="-10%" width="120%" height="125%">
    <feGaussianBlur in="SourceAlpha" stdDeviation="13.714"/>
    <feOffset dy="11.429" result="b"/>
    <feFlood flood-color="#000" flood-opacity="0.35"/>
    <feComposite in2="b" operator="in"/>
  </filter>
  <filter id="ip-soft" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="1.4"/></filter>
  <filter id="ip-blur4" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="4"/></filter>
  <filter id="ip-blur8" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="8"/></filter>
  <filter id="ip-blur12" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="12"/></filter>
  <clipPath id="ip-body-clip"><path d="{body}"/></clipPath>
  <clipPath id="ip-cap-clip"><path d="{cap}"/></clipPath>
  <clipPath id="ip-hp-disc"><circle r="{HP_R}"/></clipPath>
  <mask id="ip-hp-mask" maskUnits="userSpaceOnUse" x="-50" y="-35" width="100" height="70">
    <rect x="-50" y="-35" width="100" height="70" fill="#fff"/>
    <g transform="skewX({f(-17.5)})"><path d="{hp_letters()}" fill="#000" fill-rule="evenodd"/></g>
  </mask>
  <clipPath id="ip-groove-clip"><path d="{groove}"/></clipPath>
  <clipPath id="ip-btn-clip"><circle r="28.5"/></clipPath>
  <clipPath id="ip-pw-clip"><circle cx="{pcx}" cy="{pcy}" r="{pw['dome']}"/></clipPath>
  <clipPath id="ip-nav-clip"><circle r="45"/></clipPath>
  <g id="ip-btn">
    <circle r="{BTN_R + 1.2}" fill="#2a2014" fill-opacity="0.2"/>
    <circle r="{BTN_R}" fill="#121110"/>
    <circle r="{BTN_R - 2.2}" fill="none" stroke="url(#ip-btn-rim)" stroke-width="2"/>
    <circle r="{BTN_R - 3.6}" fill="#0c0c0c"/>
    <circle r="28.5" fill="url(#ip-btn-dome)"/>
    <circle r="28.5" fill="none" stroke="#8e887c" stroke-opacity="0.45" stroke-width="1.2"/>
  </g>
  <g id="ip-btn-hi" clip-path="url(#ip-btn-clip)">
    <path d="M-27,-6 C-20,-22 -6,-27 6,-27" fill="none" stroke="#e8e1d3" stroke-opacity="0.35" stroke-width="3" filter="url(#ip-soft)"/>
    <rect x="7" y="-14" width="9" height="31" rx="4.5" fill="#fffdf6" fill-opacity="0.95" filter="url(#ip-soft)"/>
    <path d="M-24,12 C-16,24 -2,28 14,24 C4,22 -12,20 -24,12 Z" fill="#e9dfcc" fill-opacity="0.4" filter="url(#ip-soft)"/>
    <path d="M-22,14 C-14,24 -2,27 10,25" fill="none" stroke="#b8b0a0" stroke-opacity="0.35" stroke-width="2.5" filter="url(#ip-soft)"/>
  </g>
</defs>

{group}
<g id="shadow" fill="#000" filter="url(#ip-shadow)"><path d="{body}"/></g>
<g id="device">
  <!-- body: one outline; the face colour runs into the dark side walls across the gradient -->
  <path id="body" d="{body}" fill="url(#ip-face-h)" stroke="#12100d" stroke-width="{f(ENV_STROKE)}"/>
  <g id="face" clip-path="url(#ip-body-clip)">
    <rect x="100" y="90" width="950" height="1380" fill="url(#ip-face-r)"/>
    <rect x="100" y="90" width="950" height="1380" fill="url(#ip-face-v)"/>
    <path d="{bot_edge}" fill="none" stroke="url(#ip-bot-edge)" stroke-width="16" filter="url(#ip-blur4)"/>
    <!-- the face turning under at the bottom: a chin band in the h3900 file's lightness range -->
    <path d="{bot_edge}" fill="none" stroke="#000" stroke-opacity="0.24" stroke-width="56" filter="url(#ip-blur8)"/>
    <!-- record button bulge: a grey wall with a black band inside its outer edge -->
    <path d="{bulge_wall()}" fill="#3b3731" filter="url(#ip-blur4)"/>
    <path d="{bulge_band()}" fill="none" stroke="#0f0e0d" stroke-opacity="0.95" stroke-width="16" stroke-linecap="round" filter="url(#ip-blur4)"/>
    <!-- record button housing on the left bulge: a lighter line -->
    <path d="M{f(mxl(141, 236))},{f(my(236))} C{f(mxl(144, 262))},{f(my(262))} {f(mxl(149, 286))},{f(my(286))} {f(mxl(156, 306))},{f(my(306))}" fill="none" stroke="#8c867a" stroke-opacity="0.6" stroke-width="1.6" stroke-linecap="round"/>
  </g>

  <!-- black top piece: polished cap with LEDs, grille, HP plate, power indicator and power button -->
  <g id="cap" clip-path="url(#ip-body-clip)">
    <path d="{cap}" fill="url(#ip-cap)"/>
    <g clip-path="url(#ip-cap-clip)"><g transform="{CAP_T}">
      <!-- room reflection in the polished cap: a soft light band over the right half -->
      <path d="M640,60 C660,110 676,160 700,230 L900,230 L900,60 Z" fill="url(#ip-cap-refl)" filter="url(#ip-blur8)"/>
      <ellipse cx="712" cy="84" rx="62" ry="22" fill="#f6ecd8" fill-opacity="0.75" filter="url(#ip-blur8)"/>
      <path d="M{CX - 250},70 Q{CX},58 {CX + 250},70" fill="none" stroke="#fff" stroke-opacity="0.12" stroke-width="6" filter="url(#ip-soft)"/>
      <path d="M{CX - 270},214 Q{CX},226 {CX + 250},212" fill="none" stroke="#fff" stroke-opacity="0.1" stroke-width="6" filter="url(#ip-soft)"/>
    </g></g>
    <path d="{spline([(CX - h, my(y) + 0.8) for h, y in reversed(TOP_L[1:])] + [(CX + h, my(y) + 0.8) for h, y in TOP_C], closed=False)}" fill="none" stroke="#fff" stroke-opacity="0.22" stroke-width="1.4"/>
    <g transform="{CAP_T}">
    <g id="leds">{leds}</g>
    <g id="grille" fill="none">{slots}{ridges}</g>
    </g>
    <g id="hp-plate" transform="translate({p['cx']},{f(my(p['cy']))})">
      <rect x="{-p['w'] / 2}" y="{-p['h'] / 2}" width="{p['w']}" height="{p['h']}" rx="{p['r']}" fill="url(#ip-plate)"/>
      <!-- the letters are cut out of the disc; the h's stem and the p's tail break its edge, as on the device -->
      <circle r="{HP_R}" fill="#1c1c1c" mask="url(#ip-hp-mask)"/>
    </g>
    <g id="power-indicator" transform="translate(0,{f(my(ay) - ay)})">
      <circle cx="{ax}" cy="{ay}" r="{ar}" fill="#0d0d0e"/>
      <circle cx="{ax}" cy="{ay}" r="{ar - 1.2}" fill="none" stroke="#d8d2c6" stroke-opacity="0.9" stroke-width="2.2"/>
      <circle id="led-power" aria-label="Power and charge indicator" cx="{ax}" cy="{ay}" r="{ar - 3.8}" fill="#121315"/>
      <path d="M{ax - 4.5},{ay - 3} A6,6 0 0 1 {ax + 1},{ay - 6}" fill="none" stroke="#6c6f73" stroke-opacity="0.5" stroke-width="1" pointer-events="none"/>
    </g>
    <!-- power button: chrome collar, dark ring, chrome dome with the power symbol -->
    <g transform="translate(0,{f(my(pcy) - pcy)})">
    <g id="power">
      <circle cx="{cx_}" cy="{cy_}" r="{cr_}" fill="url(#ip-pw-collar)"/>
      <circle cx="{cx_}" cy="{cy_}" r="{cr_ - 0.6}" fill="none" stroke="#1a1917" stroke-opacity="0.7" stroke-width="1.2"/>
      <path d="M{cx_ - 40},{cy_ - 13} A43,43 0 0 1 {cx_ - 8},{cy_ - 42}" fill="none" stroke="#2a2723" stroke-opacity="0.75" stroke-width="5" filter="url(#ip-soft)"/>
      <path d="M{cx_ + 27},{cy_ - 34} A44,44 0 0 1 {cx_ + 37},{cy_ + 23}" fill="none" stroke="#ffffff" stroke-width="2.2"/>
      <circle cx="{pcx}" cy="{pcy}" r="{pw['r']}" fill="#0a0a0a"/>
      <circle cx="{pcx}" cy="{pcy}" r="{pw['dome'] + 1.5}" fill="none" stroke="#5a5650" stroke-opacity="0.6" stroke-width="1.2"/>
      <circle cx="{pcx}" cy="{pcy}" r="{pw['dome']}" fill="url(#ip-pw-dome)"/>
      <g clip-path="url(#ip-pw-clip)">
        <path d="M{pcx - 25},{pcy - 3} L{pcx - 9},{pcy - 22} L{pcx - 3},{pcy - 24} L{pcx - 19},{pcy + 1} Z" fill="#8f8a80" fill-opacity="0.3"/>
        <path d="M{pcx + 5},{pcy - 10} C{pcx + 12},{pcy - 8} {pcx + 14},{pcy + 6} {pcx + 9},{pcy + 13} C{pcx + 6},{pcy + 6} {pcx + 4},{pcy - 3} {pcx + 5},{pcy - 10} Z" fill="#f4efe4" fill-opacity="0.75" filter="url(#ip-soft)"/>
        <path d="M{pcx - 15},{pcy + 17} Q{pcx},{pcy + 25} {pcx + 15},{pcy + 17}" fill="none" stroke="#6a655c" stroke-opacity="0.5" stroke-width="2.2"/>
      </g>
      <g fill="none" stroke="#c6c0b4" stroke-opacity="0.85" stroke-width="2.4" stroke-linecap="round">
        <path d="M{pcx - 8},{pcy - 13} A15.5,15.5 0 1 0 {pcx + 8},{pcy - 13}"/>
        <path d="M{pcx},{pcy - 19} V{pcy - 4}"/>
      </g>
    </g>
    </g>
  </g>

  <!-- antenna stub on the top-left shoulder -->
  <g id="antenna">
    <path d="{ant}" fill="url(#ip-ant)"/>
    <path d="{ant}" fill="url(#ip-ant-top)"/>
    <path d="M{f(ant_map(226, 90)[0])},{f(ant_map(226, 90)[1])} C{f(ant_map(230, 64)[0])},{f(ant_map(230, 64)[1])} {f(ant_map(240, 44)[0])},{f(ant_map(240, 44)[1])} {f(ant_map(262, 31)[0])},{f(ant_map(262, 31)[1])}" fill="none" stroke="#fff" stroke-opacity="0.1" stroke-width="3" stroke-linecap="round" filter="url(#ip-soft)"/>
  </g>

  <!-- dark band round the glass, with a light lip outside it -->
  <g id="frame">
    <rect x="{b0[0] - 2.5}" y="{b0[1] - 2.5}" width="{f(b0[2] - b0[0] + 5)}" height="{f(b0[3] - b0[1] + 5)}" rx="2.5" fill="#fffaf0" fill-opacity="0.22"/>
    <rect id="bezel" x="{b0[0]}" y="{b0[1]}" width="{f(b0[2] - b0[0])}" height="{f(b0[3] - b0[1])}" rx="1.5" fill="#3a3833"/>
    <rect x="{b0[0] + 0.8}" y="{b0[1] + 0.8}" width="{f(b0[2] - b0[0] - 1.6)}" height="{f(b0[3] - b0[1] - 1.6)}" rx="1" fill="none" stroke="#7d796f" stroke-opacity="0.8" stroke-width="1"/>
    <rect x="{GX - 1.2}" y="{GY - 1.2}" width="{GW + 2.4}" height="{GH + 2.4}" fill="none" stroke="#1d1c1a" stroke-width="2.4"/>
  </g>

  <g id="wordmarks">{words}</g>

  <!-- button dishes, horseshoe ridge, fingerprint groove, navigation button -->
  <g id="dishes">{dishes}</g>
  <g clip-path="url(#ip-body-clip)"><g id="ridge" transform="{PAD_T}">
    <path d="{valley_line(-6)}" fill="none" stroke="url(#ip-valley)" stroke-opacity="0.45" stroke-width="40" filter="url(#ip-blur8)"/>
    <path d="{valley_line(2)}" fill="none" stroke="url(#ip-valley)" stroke-opacity="0.75" stroke-width="22" filter="url(#ip-blur4)"/>
    <path d="{valley_line(13)}" fill="none" stroke="#fffaf0" stroke-opacity="0.45" stroke-width="3" filter="url(#ip-soft)"/>
    <path d="{valley_line(-34, 3)}" fill="none" stroke="#fffaf0" stroke-opacity="0.25" stroke-width="22" filter="url(#ip-blur8)"/>
  </g></g>
  <g id="groove" transform="{PAD_T}">
    <path d="{groove}" fill="url(#ip-groove)"/>
    <rect x="490" y="{SENSOR[0]}" width="170" height="{f(SENSOR[1] - SENSOR[0])}" fill="#3a362f" clip-path="url(#ip-groove-clip)"/>
    <path d="M490,{SENSOR[1] + 0.8} H660" stroke="#fffaf0" stroke-opacity="0.2" stroke-width="1.4" clip-path="url(#ip-groove-clip)"/>
    <path d="M514,1262 C513,1320 512,1380 512,1420" fill="none" stroke="#2a2014" stroke-opacity="0.18" stroke-width="7" filter="url(#ip-soft)"/>
    <path d="{wall_l}" fill="#47433b"/>
    <path d="{wall_r}" fill="#4d4940"/>
    <path d="M509,1262 C503,1310 501.5,1380 502,1412" fill="none" stroke="#fffaf0" stroke-opacity="0.4" stroke-width="1.4" transform="translate(-2.5,0)"/>
  </g>
  <g id="navigation" transform="translate({n['cx']},{f(my(n['cy']))}) scale({K_PAD})">
    <circle r="78" fill="#2a2014" fill-opacity="0.14" filter="url(#ip-soft)"/>
    <circle r="75.5" fill="url(#ip-nav-ring)"/>
    <circle r="67" fill="none" stroke="#3a352d" stroke-width="2"/>
    <circle r="63.5" fill="none" stroke="#8a8274" stroke-width="5"/>
    <circle r="59" fill="none" stroke="url(#ip-nav-chrome)" stroke-width="4"/>
    <circle r="56.8" fill="#24211d"/>
    <circle r="54" fill="none" stroke="#5a554c" stroke-opacity="0.5" stroke-width="2" filter="url(#ip-soft)"/>
    <circle r="47" fill="none" stroke="url(#ip-nav-chrome)" stroke-width="2.6"/>
    <circle r="45" fill="url(#ip-nav-disc)"/>
    <g clip-path="url(#ip-nav-clip)">
      <path d="M2,-28 C12,-30 22,-26 28,-20 C20,-22 10,-23 2,-28 Z" fill="#a49d90" fill-opacity="0.5" filter="url(#ip-soft)"/>
      <path d="M34,-26 C44,-12 46,10 36,30 C38,12 38,-8 34,-26 Z" fill="#9c958a" fill-opacity="0.55" filter="url(#ip-soft)"/>
      <path d="M-18,36 C-2,22 6,2 8,-16" fill="none" stroke="#7a756c" stroke-opacity="0.5" stroke-width="1.2"/>
      <path d="M-34,26 C-22,40 0,44 22,38" fill="none" stroke="#c9c3b7" stroke-opacity="0.4" stroke-width="2.5" filter="url(#ip-soft)"/>
      <path d="M-26,-30 C-18,-32 -12,-26 -12,-14 L-12,14 C-12,24 -18,30 -26,30 C-35,26 -40,12 -40,0 C-40,-14 -35,-26 -26,-30 Z" fill="#fffef8" fill-opacity="0.96" filter="url(#ip-soft)"/>
    </g>
  </g>
  <g id="microphone" transform="{PAD_T}">{mic}</g>
  <g id="app-buttons">{buttons}</g>
</g>
</g>

<!-- glass slot in SVG units: a neutral placeholder until a screenshot is composited -->
<rect id="screen" x="{f(GLASS_U[0])}" y="{f(GLASS_U[1])}" width="{GLASS_U[2]}" height="{GLASS_U[3]}" fill="#c3c6c9"/>
<rect id="glass" x="{f(GLASS_U[0])}" y="{f(GLASS_U[1])}" width="{GLASS_U[2]}" height="{GLASS_U[3]}" fill="url(#ip-glass)" pointer-events="none"/>
</svg>
'''
        return neutral(out)

    return build()


def rounded(pts, radii):
    """Closed polygon with each corner rounded by a quadratic of the given cut-back."""
    n = len(pts)
    d = ''
    for i in range(n):
        prv, cur, nxt = pts[i - 1], pts[i], pts[(i + 1) % n]
        r = radii[i]
        def toward(a, b, dist):
            dx, dy = b[0] - a[0], b[1] - a[1]
            ln = math.hypot(dx, dy)
            k = min(dist / ln, 0.5) if ln else 0
            return (a[0] + dx * k, a[1] + dy * k)
        a = toward(cur, prv, r)
        b = toward(cur, nxt, r)
        d += ('M' if i == 0 else ' L') + f'{f(a[0])},{f(a[1])} Q{f(cur[0])},{f(cur[1])} {f(b[0])},{f(b[1])}'
    return d + ' Z'


def hp_monogram(R):
    """The slanted hp letters on a badge disc of radius R, as one path."""
    # hp letters on a unit grid (disc radius 1), slanted strokes
    sl = 0.32   # horizontal shift per unit of height (italic slant)
    def bar(xc, y0, y1, w=0.21):
        # parallelogram bar from y0 to y1 (unit coords), centred on xc at y=0
        return (f'M{f((xc - w/2 - sl*y0) * R)},{f(y0 * R)} L{f((xc + w/2 - sl*y0) * R)},{f(y0 * R)} '
            f'L{f((xc + w/2 - sl*y1) * R)},{f(y1 * R)} L{f((xc - w/2 - sl*y1) * R)},{f(y1 * R)} Z')
    return (bar(-0.40, -1.02, 0.42) + bar(-0.02, -0.20, 0.42) + bar(0.20, -0.20, 1.12) + bar(0.58, -0.20, 0.42)
                  + f' M{f((-0.40 + 0.085 - sl*-0.1)*R)},{f(-0.1*R)} Q{f((-0.05 - sl*-0.3)*R)},{f(-0.32*R)} {f((-0.02 + 0.085 - sl*-0.16)*R)},{f(-0.16*R)}'
              f' L{f((-0.02 - 0.085 - sl*-0.03)*R)},{f(-0.03*R)} Q{f((-0.14 - sl*-0.12)*R)},{f(-0.14*R)} {f((-0.40 + 0.085 - sl*0.06)*R)},{f(0.06*R)} Z'
                  + f' M{f((0.20 + 0.085 - sl*-0.1)*R)},{f(-0.1*R)} Q{f((0.55 - sl*-0.3)*R)},{f(-0.32*R)} {f((0.58 + 0.085 - sl*-0.16)*R)},{f(-0.16*R)}'
              f' L{f((0.58 - 0.085 - sl*-0.03)*R)},{f(-0.03*R)} Q{f((0.42 - sl*-0.12)*R)},{f(-0.14*R)} {f((0.20 + 0.085 - sl*0.06)*R)},{f(0.06*R)} Z'
                  + f' M{f((0.20 + 0.085 - sl*0.36)*R)},{f(0.36*R)} Q{f((0.45 - sl*0.5)*R)},{f(0.48*R)} {f((0.58 - 0.085 - sl*0.3)*R)},{f(0.3*R)}'
              f' L{f((0.58 + 0.085 - sl*0.36)*R)},{f(0.36*R)} Q{f((0.5 - sl*0.62)*R)},{f(0.62*R)} {f((0.20 + 0.085 - sl*0.5)*R)},{f(0.5*R)} Z')


def build_hx4700(fonts):
    """Draw the hx4700 from measured photo coordinates."""
    GX, GY, GW, GH = 1100, 1650, 1776, 2368     # glass in photo px
    GLASS_U = (137.5, 244.75, 525, 700)        # glass in SVG units
    S = GLASS_U[2] / GW                         # units per photo px (0.29561)
    TX = GLASS_U[0] - GX * S
    TY = GLASS_U[1] - GY * S
    K = 2.1875                                  # units per CSS px (h2200/h3900 canvas)
    CSS_W, CSS_H = 366, 556
    VB_X, VB_Y = -0.3125, -0.25
    VB_W, VB_H = CSS_W * K, CSS_H * K
    CX = GX + GW / 2                            # 1988, the device centre line

    # ---- measured geometry (photo px; x as offset from the centre line) --------
    # Body silhouette, right half, (half-width, y) top to bottom; mirrored.
    BODY_HALF = [
        (0, 913), (500, 918), (700, 928), (860, 944), (940, 958), (990, 968),
        (1046, 986), (1069, 1001), (1082, 1026), (1088, 1062), (1088, 1400),
        (1088, 4300), (1088, 4600), (1085, 4648), (1072, 4682), (1010, 4712),
        (890, 4752), (840, 4764), (700, 4766), (0, 4766),
    ]
    # Front plane of the face, inside the rounded edge band that turns away.
    FACE_HALF = [
        (0, 962), (500, 965), (800, 975), (985, 990), (1046, 998), (1072, 1008),
        (1079, 1030), (1080, 1070), (1080, 1400), (1080, 4300), (1080, 4600),
        (1076, 4640), (1062, 4668), (1000, 4692), (884, 4733), (840, 4740), (700, 4741), (0, 4741),
    ]

    # Black top cap: its diagonal sides follow half-width h(y) = 719 + 0.477 (1300 - y).
    CAP_H0, CAP_SLOPE = 719, 0.477
    CAP_LEFT_Y = 1133          # left of its diagonal the cap runs out to the body edge above this line
    CAP_BOT = 1468             # bottom edge
    CAP_R_TOP, CAP_R_BOT = 22, 50

    # Screen opening (glass px): black border 35 px, recess walls 57 (sides) and 66 (top, bottom).
    BORDER = 35
    WALL_SIDE, WALL_TB = 57, 66
    OPEN_R = 10

    # Lower black panel: top edge y 4210, sides h(y) = 670 + 0.45 (y - 4220).
    BP_TOP, BP_H0, BP_SLOPE, BP_R = 4210, 650, 0.45, 58
    # Recessed navigation pad (rounded trapezoid) on the panel.
    PAD = dict(top=4255, bot=4690, ht=372, hb=495, rt=46, rb=62)
    PAD_DOTS = [(0, 4328), (-327, 4463), (327, 4463), (0, 4599)]
    # Printed application glyphs: (rel x, y, kind, width, height)
    ICONS = [(-570, 4329, 'contacts', 84, 65), (571, 4327, 'mail', 89, 67),
             (-690, 4592, 'calendar', 85, 72), (664 + 34, 4580, 'ok', 58, 90)]
    LABEL_DY = {'contacts': 54, 'mail': 54, 'calendar': 55, 'ok': 62}

    # LED windows down the cap's left diagonal and the wireless mark above them.
    LEDS = [(-704, 1178), (-665, 1266), (-625, 1350)]
    LED_W, LED_L, LED_ANG = 22, 56, -25.5
    WIFI = (-648, 1156)
    # Speaker: 3 rows of 3 slanted slots along the right diagonal (slot centres).
    SPEAKER = [[(614, 1183), (679, 1183), (743, 1183)],
               [(573, 1270), (638, 1270), (703, 1270)],
               [(532, 1357), (595, 1357), (660, 1357)]]
    SLOT_L, SLOT_ANG = 54, 25.5
    # hp badge: chrome plate and the dark disc on it.
    BADGE = dict(x=8, y=1216, w=259, h=163, r=20, dx=6, dy=-5, R=78)
    # Microphone hole on the face, lower right.
    MIC = (959, 4479, 22, 27)


    IPAQ = dict(text='iPAQ', font='OpenSans_Bold.ttf', x0=-872, x1=-716, base=4262, cap=54)
    # -----------------------------------------------------------------------------











    def cap_h(y):
        return CAP_H0 + CAP_SLOPE * (1300 - y)


    def bp_h(y):
        return BP_H0 + BP_SLOPE * (y - 4220)


    def word_path(text, font_file, x0, x1, base, cap):
        return fonts.word_path(text, font_file, cap, x0, base, 'start', x1 - x0)


    def speckle_tile(seed, size=48, n=46):
        """A tile of small light and dark grains, the sparkle finish of the hx4700 face."""
        rnd = random.Random(seed)
        out = []
        for i in range(n):
            x, y = rnd.uniform(0, size), rnd.uniform(0, size)
            r = rnd.uniform(1.6, 3.4)
            light = i % 2 == 0
            op = rnd.uniform(0.16, 0.42) if light else rnd.uniform(0.18, 0.4)
            col = '#fff' if light else '#000'
            for ox in (-size, 0, size):
                for oy in (-size, 0, size):
                    xx, yy = x + ox, y + oy
                    if -r < xx < size + r and -r < yy < size + r:
                        out.append(f'<circle cx="{f(xx)}" cy="{f(yy)}" r="{f(r)}" fill="{col}" fill-opacity="{f(op)}"/>')
        return ''.join(out)


    ICON_SVG = {
        # Drawn on a box of the measured size centred on (0,0); stroke 6 photo px.
        'contacts': lambda w, h: (
            f'<rect x="{f(-w/2+3)}" y="{f(-h/2+3)}" width="{f(w-6)}" height="{f(h-6)}" fill="none" stroke-width="6"/>'
        f'<path d="M{f(-w/2+31)},{f(-h/2+3)} V{f(h/2-3)}" stroke-width="5"/>'
        f'<rect x="{f(-w/2+10)}" y="{f(-h/2+9)}" width="14" height="19" rx="2" fill="#dcdcdc" stroke="none"/>'
            + ''.join(f'<path d="M{f(-w/2+41)},{f(-h/2+16+i*12.5)} H{f(w/2-10)}" stroke-width="5.5" stroke-linecap="round"/>' for i in range(4))),
        'mail': lambda w, h: (
            f'<rect x="{f(-w/2+3)}" y="{f(-h/2+3)}" width="{f(w-6)}" height="{f(h-6)}" fill="none" stroke-width="6"/>'
        f'<path d="M{f(-w/2+4)},{f(-h/2+4)} L0,{f(h*0.08)} L{f(w/2-4)},{f(-h/2+4)} M{f(-w/2+4)},{f(h/2-4)} L{f(-w*0.1)},{f(-h*0.02)} M{f(w/2-4)},{f(h/2-4)} L{f(w*0.1)},{f(-h*0.02)}" fill="none" stroke-width="5" stroke-linejoin="round"/>'),
        'calendar': lambda w, h: (
            f'<rect x="{f(-w/2+3)}" y="{f(-h/2+3)}" width="{f(w-6)}" height="{f(h-6)}" fill="none" stroke-width="6"/>'
        f'<rect x="{f(-w/2+3)}" y="{f(-h/2+3)}" width="{f(w-6)}" height="13" fill="#dcdcdc" stroke="none"/>'
            + ''.join(f'<path d="M{f(-w/2+3+(w-6)*i/4)},{f(-h/2+14)} V{f(h/2-3)}" stroke-width="5"/>' for i in (1, 2, 3))
            + ''.join(f'<path d="M{f(-w/2+3)},{f(-h/2+14+(h-17)*j/3)} H{f(w/2-3)}" stroke-width="5"/>' for j in (1, 2))
            + f'<rect x="{f(-w/2+3+(w-6)*2/4)}" y="{f(-h/2+14+(h-17)/3)}" width="{f((w-6)/4)}" height="{f((h-17)/3)}" fill="#c9c9c9" stroke="none"/>'),
        'ok': lambda w, h: (
            # a C-shaped arrow, open to the right, ending in a head pointing up and right
            f'<path d="M{f(w*0.18)},{f(h*0.44)} C{f(-w*0.42)},{f(h*0.52)} {f(-w*0.46)},{f(-h*0.02)} {f(-w*0.02)},{f(-h*0.22)}" fill="none" stroke-width="8" stroke-linecap="round"/>'
        f'<path d="M{f(-w*0.16)},{f(-h*0.30)} L{f(w*0.46)},{f(-h*0.50)} L{f(w*0.18)},{f(-h*0.02)} Z" fill="#dcdcdc" stroke="none"/>'),
    }


    def build():
        body = spline(mirror(BODY_HALF, CX))
        face = spline(mirror(FACE_HALF, CX))
        # face top front edge (open), used for the highlight
        top = [p for p in FACE_HALF if p[1] < 1100]
        top_edge = spline([(CX - h, y) for h, y in reversed(top)] + [(CX + h, y) for h, y in top[1:]], closed=False)
        bot = [p for p in FACE_HALF if p[1] > 4500]
        bot_edge = spline([(CX - h, y) for h, y in bot] + [(CX + h, y) for h, y in reversed(bot[:-1])], closed=False)

        # black top cap, clipped later by the body
        cap_pts = [(CX - 1300, 800), (CX - 1300, CAP_LEFT_Y), (CX - cap_h(CAP_LEFT_Y), CAP_LEFT_Y),
                   (CX - cap_h(CAP_BOT), CAP_BOT), (CX + cap_h(CAP_BOT), CAP_BOT), (CX + cap_h(800), 800)]
        cap = rounded(cap_pts, [0, 0, CAP_R_TOP, CAP_R_BOT, CAP_R_BOT, 0])
        # the cap's visible edge lines on the face
        cap_edge_r = f'M{f(CX + cap_h(CAP_BOT - 30))},{f(CAP_BOT - 30)} L{f(CX + cap_h(985))},985'
        cap_edge_b = f'M{f(CX - cap_h(CAP_BOT) + 30)},{CAP_BOT} H{f(CX + cap_h(CAP_BOT) - 30)}'

        bp_pts = [(CX - bp_h(BP_TOP), BP_TOP), (CX + bp_h(BP_TOP), BP_TOP), (CX + bp_h(4900), 4900), (CX - bp_h(4900), 4900)]
        bpanel = rounded(bp_pts, [BP_R, BP_R, 0, 0])
        p = PAD
        pad = rounded([(CX - p['ht'], p['top']), (CX + p['ht'], p['top']), (CX + p['hb'], p['bot']), (CX - p['hb'], p['bot'])],
                      [p['rt'], p['rt'], p['rb'], p['rb']])

        o0 = (GX - BORDER - WALL_SIDE, GY - BORDER - WALL_TB, GX + GW + BORDER + WALL_SIDE, GY + GH + BORDER + WALL_TB)
        o1 = (GX - BORDER, GY - BORDER, GX + GW + BORDER, GY + GH + BORDER)

        head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{CSS_W}" height="{CSS_H}" '
            f'viewBox="{VB_X!r} {VB_Y!r} {VB_W!r} {VB_H!r}">\n')
        group = f'<g transform="matrix({S:.6f} 0 0 {S:.6f} {TX:.4f} {TY:.4f})">'

        ipaq = word_path(IPAQ['text'], IPAQ['font'], CX + IPAQ['x0'], CX + IPAQ['x1'], IPAQ['base'], IPAQ['cap'])

        # The User's Guide puts the blue Wi-Fi/Bluetooth light top left; the order of the other two is unverified.
        names = (('wireless', 'Wi-Fi and Bluetooth'), ('notification', 'Notification'), ('power', 'Power and charge'))
        leds = ''.join(
            f'<g transform="translate({f(CX + x)},{y}) rotate({LED_ANG})">'
        f'<rect x="{f(-LED_W/2 - 3)}" y="{f(-LED_L/2 - 3)}" width="{LED_W + 6}" height="{LED_L + 6}" rx="5" fill="#050506"/>'
        f'<rect id="led-{n}" aria-label="{label} indicator" x="{f(-LED_W/2)}" y="{f(-LED_L/2)}" width="{LED_W}" height="{LED_L}" rx="2" fill="#a1a2a4"/>'
        f'<g pointer-events="none"><rect x="{f(-LED_W/2)}" y="{f(-LED_L/2)}" width="{LED_W}" height="{LED_L}" rx="2" fill="url(#hx-led)"/>'
        f'<circle cx="{f(LED_W/2 - 3)}" cy="{f(LED_L/2 - 2)}" r="4" fill="#fff" fill-opacity="0.8"/></g></g>'
            for (x, y), (n, label) in zip(LEDS, names))
        wx, wy = WIFI
        wifi = (f'<g transform="translate({f(CX + wx)},{wy})" fill="none" stroke="#f2f2f2" stroke-linecap="round">'
            f'<path d="M-15,-14 A20,20 0 0 0 -15,14 M15,-14 A20,20 0 0 1 15,14" stroke-width="6"/>'
            f'<path d="M-28,-24 A36,36 0 0 0 -28,24 M28,-24 A36,36 0 0 1 28,24" stroke-width="6.5"/>'
            f'<circle cx="0" cy="-4" r="7" fill="#f2f2f2" stroke="none"/>'
            f'<path d="M-3.5,0 L-6,34 L6,34 L3.5,0 Z" fill="#f2f2f2" stroke="none"/></g>')
        slots = ''.join(
            f'<g transform="translate({f(CX + x)},{y}) rotate({SLOT_ANG})">'
        f'<rect x="-12" y="{f(-SLOT_L/2)}" width="18" height="{SLOT_L}" rx="8" fill="url(#hx-slot)"/>'
        f'<path d="M4,{f(-SLOT_L/2 + 4)} V{f(SLOT_L/2 - 3)}" stroke="#f4f4f4" stroke-width="4.5" stroke-linecap="round"/></g>'
            for row in SPEAKER for x, y in row)

        b = BADGE
        bx, by = CX + b['x'], b['y']
        R = b['R']
        hp_letters = hp_monogram(R)
        badge = (f'<g id="badge" transform="translate({f(bx)},{by})">'
             f'<rect x="{f(-b["w"]/2 - 4)}" y="{f(-b["h"]/2 - 4)}" width="{b["w"] + 8}" height="{b["h"] + 8}" rx="{b["r"] + 4}" fill="#050506"/>'
             f'<rect x="{f(-b["w"]/2)}" y="{f(-b["h"]/2)}" width="{b["w"]}" height="{b["h"]}" rx="{b["r"]}" fill="url(#hx-plate)"/>'
             f'<clipPath id="hx-plate-clip"><rect x="{f(-b["w"]/2)}" y="{f(-b["h"]/2)}" width="{b["w"]}" height="{b["h"]}" rx="{b["r"]}"/></clipPath>'
             f'<rect clip-path="url(#hx-plate-clip)" x="{f(-b["w"]/2)}" y="{f(-b["h"]/2)}" width="{b["w"]}" height="{b["h"]}" filter="url(#hx-grain)" opacity="0.12"/>'
             f'<rect x="{f(-b["w"]/2 + 3)}" y="{f(-b["h"]/2 + 3)}" width="{b["w"] - 6}" height="{b["h"] - 6}" rx="{b["r"] - 3}" fill="none" stroke="#fff" stroke-opacity="0.7" stroke-width="4"/>'
             f'<g transform="translate({b["dx"]},{b["dy"]})">'
             f'<circle r="{R}" fill="url(#hx-disc)"/>'
             f'<path d="M{f(R * math.cos(math.radians(-70)))},{f(R * math.sin(math.radians(-70)))} A{R},{R} 0 0 1 {f(R * math.cos(math.radians(105)))},{f(R * math.sin(math.radians(105)))}" fill="none" stroke="#f4f4f4" stroke-width="8"/>'
             f'<path d="{hp_letters}" fill="url(#hx-letters)"/></g></g>')

        icons = ''
        for x, y, kind, w, h in ICONS:
            icons += (f'<g transform="translate({f(CX + x)},{y})" stroke="#dcdcdc" fill="none">{ICON_SVG[kind](w, h)}</g>'
                  f'<path d="M{f(CX + x - 20)},{y + LABEL_DY[kind]} h40" stroke="#9a9a9e" stroke-opacity="0.3" stroke-width="4" stroke-linecap="round"/>')
        dots = ''.join(f'<circle cx="{f(CX + x)}" cy="{y}" r="6" fill="#d8d8da" fill-opacity="0.85"/>' for x, y in PAD_DOTS)
        mx, my, mrx, mry = MIC

        walls = (
            f'<polygon id="wall-top" points="{o0[0]},{o0[1]} {o0[2]},{o0[1]} {o1[2]},{o1[1]} {o1[0]},{o1[1]}" fill="url(#hx-wall-top)"/>'
        f'<polygon id="wall-bottom" points="{o0[0]},{o0[3]} {o0[2]},{o0[3]} {o1[2]},{o1[3]} {o1[0]},{o1[3]}" fill="url(#hx-wall-bot)"/>'
        f'<polygon id="wall-left" points="{o0[0]},{o0[1]} {o1[0]},{o1[1]} {o1[0]},{o1[3]} {o0[0]},{o0[3]}" fill="url(#hx-wall-l)"/>'
        f'<polygon id="wall-right" points="{o0[2]},{o0[1]} {o1[2]},{o1[1]} {o1[2]},{o1[3]} {o0[2]},{o0[3]}" fill="url(#hx-wall-r)"/>')
        opening = f'M{o0[0]},{o0[1]} H{o0[2]} V{o0[3]} H{o0[0]} Z'

        return head + f'''<!--
  HP iPAQ hx4700, front view. Glass: <rect id="screen"> x={f(GLASS_U[0])} y={f(GLASS_U[1])} width={GLASS_U[2]} height={GLASS_U[3]} (3:4, 480x640 px at 1.09375 units per pixel; the same glass size as the 240x320 frames).

  SPDX-FileCopyrightText: 2026 Koen Kooi
  SPDX-License-Identifier: CC-BY-SA-4.0

  Provenance: an original vector drawing, written as SVG geometry and
  gradients and drawn with the assistance of Claude (Opus 5.5) from a
  reference photograph: HP iPAQ hx4700 - Front.jpg by Beamish4
  (CC BY-SA 4.0), from Wikimedia Commons, and from the h3900 drawing of the
  same project. No third-party artwork was traced or embedded. The printed
  "iPAQ" is glyph outlines from the Open Sans font (SIL Open Font License);
  the hp badge is drawn from simple shapes. "HP", "hp" and "iPAQ" are
  trademarks of their owners and appear only to identify the device.
-->
<defs>
  <linearGradient id="hx-face-v" gradientUnits="userSpaceOnUse" x1="0" y1="960" x2="0" y2="4720">
    <stop offset="0" stop-color="#726e6c"/>
    <stop offset="0.16" stop-color="#5a5759"/>
    <stop offset="0.5" stop-color="#454346"/>
    <stop offset="0.86" stop-color="#353336"/>
    <stop offset="1" stop-color="#2f2d30"/>
  </linearGradient>
  <linearGradient id="hx-face-h" gradientUnits="userSpaceOnUse" x1="{f(CX - 1090)}" y1="0" x2="{f(CX + 1090)}" y2="0">
    <stop offset="0" stop-color="#fff" stop-opacity="0.22"/>
    <stop offset="0.012" stop-color="#fff" stop-opacity="0.1"/>
    <stop offset="0.12" stop-color="#fff" stop-opacity="0.05"/>
    <stop offset="0.5" stop-color="#000" stop-opacity="0"/>
    <stop offset="0.88" stop-color="#000" stop-opacity="0.16"/>
    <stop offset="1" stop-color="#000" stop-opacity="0.24"/>
  </linearGradient>
  <linearGradient id="hx-roll" gradientUnits="userSpaceOnUse" x1="0" y1="913" x2="0" y2="4765">
    <stop offset="0" stop-color="#5b585b"/><stop offset="0.03" stop-color="#3a383b"/>
    <stop offset="0.97" stop-color="#2a282b"/><stop offset="1" stop-color="#18171a"/>
  </linearGradient>
  <pattern id="hx-speckle" width="48" height="48" patternUnits="userSpaceOnUse">{speckle_tile(4700)}</pattern>
  <pattern id="hx-speckle-fine" width="40" height="40" patternUnits="userSpaceOnUse">{speckle_tile(4701, 40, 30)}</pattern>
  <linearGradient id="hx-cap" gradientUnits="userSpaceOnUse" x1="0" y1="913" x2="0" y2="{CAP_BOT}">
    <stop offset="0" stop-color="#2a2427"/><stop offset="0.1" stop-color="#1a1719"/>
    <stop offset="0.4" stop-color="#121114"/><stop offset="1" stop-color="#0d0d10"/>
  </linearGradient>
  <linearGradient id="hx-cap-sheen" gradientUnits="userSpaceOnUse" x1="{f(CX - 900)}" y1="1000" x2="{f(CX + 300)}" y2="1500">
    <stop offset="0" stop-color="#fff" stop-opacity="0.07"/><stop offset="0.45" stop-color="#fff" stop-opacity="0.02"/>
    <stop offset="1" stop-color="#fff" stop-opacity="0"/>
  </linearGradient>
  <linearGradient id="hx-panel" gradientUnits="userSpaceOnUse" x1="0" y1="{BP_TOP}" x2="0" y2="4765">
    <stop offset="0" stop-color="#1e1d21"/><stop offset="0.85" stop-color="#18171a"/><stop offset="1" stop-color="#0e0d10"/>
  </linearGradient>
  <linearGradient id="hx-pad" gradientUnits="userSpaceOnUse" x1="0" y1="{PAD['top']}" x2="0" y2="{PAD['bot']}">
    <stop offset="0" stop-color="#232326"/><stop offset="0.2" stop-color="#2b2b2e"/><stop offset="1" stop-color="#29292c"/>
  </linearGradient>
  <linearGradient id="hx-wall-top" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#46434a"/><stop offset="1" stop-color="#38353a"/>
  </linearGradient>
  <linearGradient id="hx-wall-bot" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#a9a6a8"/><stop offset="1" stop-color="#8c898c"/>
  </linearGradient>
  <linearGradient id="hx-wall-l" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#555256"/><stop offset="1" stop-color="#403d41"/>
  </linearGradient>
  <linearGradient id="hx-wall-r" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#77747a"/><stop offset="1" stop-color="#626064"/>
  </linearGradient>
  <linearGradient id="hx-glass" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#fff" stop-opacity="0.06"/>
    <stop offset="0.45" stop-color="#fff" stop-opacity="0.012"/>
    <stop offset="1" stop-color="#fff" stop-opacity="0"/>
  </linearGradient>
  <linearGradient id="hx-led" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#000" stop-opacity="0.14"/><stop offset="0.45" stop-color="#fff" stop-opacity="0.18"/><stop offset="1" stop-color="#000" stop-opacity="0.26"/>
  </linearGradient>
  <linearGradient id="hx-slot" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#3a3134" stop-opacity="0"/><stop offset="0.35" stop-color="#3a3134" stop-opacity="0.75"/><stop offset="1" stop-color="#000" stop-opacity="0.95"/>
  </linearGradient>
  <linearGradient id="hx-plate" x1="0" y1="0" x2="0.35" y2="1">
    <stop offset="0" stop-color="#e9eaea"/><stop offset="0.35" stop-color="#bfc0c0"/>
    <stop offset="0.7" stop-color="#a9aaab"/><stop offset="1" stop-color="#d6d7d7"/>
  </linearGradient>
  <radialGradient id="hx-disc" cx="0.5" cy="0.5" r="0.5" fx="0.42" fy="0.38">
    <stop offset="0" stop-color="#4a4246"/><stop offset="0.8" stop-color="#2b2629"/><stop offset="1" stop-color="#1e1a1c"/>
  </radialGradient>
  <linearGradient id="hx-letters" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#fafafa"/><stop offset="1" stop-color="#cfd0d1"/>
  </linearGradient>
  <filter id="hx-shadow" x="-15%" y="-10%" width="130%" height="125%">
    <feGaussianBlur in="SourceAlpha" stdDeviation="{f(12 / S)}"/>
    <feOffset dy="{f(10 / S)}" result="b"/>
    <feFlood flood-color="#000" flood-opacity="0.35"/>
    <feComposite in2="b" operator="in"/>
  </filter>
  <filter id="hx-grain" x="0" y="0" width="1" height="1">
    <feTurbulence type="fractalNoise" baseFrequency="0.21" numOctaves="2" seed="47" result="n"/>
    <feColorMatrix in="n" type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  4.2 0 0 0 -2.05" result="light"/>
    <feColorMatrix in="n" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  -3.4 0 0 0 1.5" result="dark"/>
    <feMerge><feMergeNode in="dark"/><feMergeNode in="light"/></feMerge>
  </filter>
  <filter id="hx-soft" x="-30%" y="-30%" width="160%" height="160%">
    <feGaussianBlur stdDeviation="6"/>
  </filter>
  <clipPath id="hx-body-clip"><path d="{body}"/></clipPath>
  <clipPath id="hx-face-clip"><path d="{face}"/></clipPath>
  <clipPath id="hx-cap-clip"><path d="{cap}"/></clipPath>
  <clipPath id="hx-bp-clip"><path d="{bpanel}"/></clipPath>
  <clipPath id="hx-pad-clip"><path d="{pad}"/></clipPath>
</defs>

{group}
<g id="shadow" fill="#000" filter="url(#hx-shadow)"><path d="{body}"/></g>
<g id="device">
  <!-- body: the rounded edge band that turns away from the viewer, then the front plane -->
  <g id="face">
    <path id="body-edge" d="{body}" fill="url(#hx-roll)"/>
    <path d="{body}" fill="url(#hx-face-h)"/>
    <g clip-path="url(#hx-body-clip)"><rect x="{f(CX - 1100)}" y="900" width="2200" height="3900" filter="url(#hx-grain)" opacity="0.3"/></g>
    <clipPath id="hx-top-band"><rect x="{f(CX - 1200)}" y="880" width="2400" height="200"/></clipPath>
    <path d="{body} {face}" fill-rule="evenodd" fill="#7b787b" fill-opacity="0.55" clip-path="url(#hx-top-band)"/>
    <path id="face-base" d="{face}" fill="url(#hx-face-v)"/>
    <g clip-path="url(#hx-face-clip)">
      <rect x="{f(CX - 1100)}" y="900" width="2200" height="3900" fill="url(#hx-face-h)"/>
      <rect x="{f(CX - 1100)}" y="900" width="2200" height="3900" filter="url(#hx-grain)" opacity="0.62"/>
    </g>
    <path d="{face}" fill="none" stroke="#000" stroke-opacity="0.35" stroke-width="3"/>
  </g>

  <!-- black gloss cap across the top: hp badge, LED windows, speaker -->
  <g id="cap" clip-path="url(#hx-body-clip)">
    <path d="{cap}" fill="url(#hx-cap)"/>
    <path d="{cap}" fill="url(#hx-cap-sheen)"/>
    <path d="{body} {face}" fill-rule="evenodd" fill="#3b2f33" fill-opacity="0.22" clip-path="url(#hx-cap-clip)"/>
    <path d="{cap_edge_r}" stroke="#e8e8e8" stroke-opacity="0.85" stroke-width="5" stroke-linecap="round"/>
    <path d="{cap_edge_b}" stroke="#000" stroke-opacity="0.5" stroke-width="5"/>
  </g>
  <!-- the front edge of the top, catching the light -->
  <path id="top-edge" d="{top_edge}" fill="none" stroke="#fff" stroke-opacity="0.22" stroke-width="3.5"/>
  <path d="M{f(CX - 1074)},1012 Q{f(CX - 1060)},1000 {f(CX - 985)},991 L{f(CX - 820)},977" fill="none" stroke="#fff" stroke-opacity="0.7" stroke-width="5" stroke-linecap="round"/>
  <g id="leds">{leds}{wifi}</g>
  <g id="speaker">{slots}</g>
  {badge}

  <!-- recessed screen opening: mitred walls lit from the top left, black border, glass -->
  <g id="frame">
    {walls}
    <clipPath id="hx-lit-walls"><polygon points="{o0[0]},{o0[3]} {o0[2]},{o0[3]} {o0[2]},{o0[1]} {o1[2]},{o1[1]} {o1[2]},{o1[3]} {o1[0]},{o1[3]}"/></clipPath>
    <path d="{opening} M{o1[0]},{o1[1]} V{o1[3]} H{o1[2]} V{o1[1]} Z" fill="#000" fill-opacity="0"/>
    <clipPath id="hx-walls"><path d="{opening} M{o1[0]},{o1[1]} V{o1[3]} H{o1[2]} V{o1[1]} Z"/></clipPath>
    <rect clip-path="url(#hx-walls)" x="{o0[0]}" y="{o0[1]}" width="{o0[2]-o0[0]}" height="{o0[3]-o0[1]}" filter="url(#hx-grain)" opacity="0.45"/>
    <rect clip-path="url(#hx-lit-walls)" x="{o0[0]}" y="{o0[1]}" width="{o0[2]-o0[0]}" height="{o0[3]-o0[1]}" filter="url(#hx-grain)" opacity="0.5"/>
    <path d="{opening}" fill="none"/>
    <rect x="{o0[0]}" y="{o0[1]}" width="{o0[2]-o0[0]}" height="{o0[3]-o0[1]}" rx="{OPEN_R}" fill="none" stroke="#000" stroke-opacity="0.3" stroke-width="3"/>
    <rect id="bezel" x="{o1[0]}" y="{o1[1]}" width="{o1[2]-o1[0]}" height="{o1[3]-o1[1]}" fill="#0f0f13"/>
  </g>

  <!-- lower black panel with the recessed navigation pad and the printed glyphs -->
  <g id="lower" clip-path="url(#hx-body-clip)">
    <path d="{bpanel}" fill="url(#hx-panel)"/>
    <path d="{bpanel}" fill="none" stroke="#8a898e" stroke-opacity="0.45" stroke-width="4"/>
    <rect clip-path="url(#hx-bp-clip)" x="{f(CX - 1000)}" y="4716" width="2000" height="80" fill="#0b0b0d"/>
    <path d="M{f(CX - bp_h(4716))},4716 H{f(CX + bp_h(4716))}" stroke="#a9a8ad" stroke-opacity="0.55" stroke-width="3.5"/>
    <path id="pad" d="{pad}" fill="url(#hx-pad)"/>
    <g clip-path="url(#hx-pad-clip)"><rect x="{f(CX - 520)}" y="{PAD['top']}" width="1040" height="{PAD['bot'] - PAD['top']}" filter="url(#hx-grain)" opacity="0.22"/>
      <path d="{pad}" fill="none" stroke="#000" stroke-opacity="0.45" stroke-width="10" filter="url(#hx-soft)"/></g>
    <path d="{pad}" fill="none" stroke="#5c5b60" stroke-opacity="0.8" stroke-width="3"/>
    {dots}
    <g id="app-glyphs">{icons}</g>
  </g>
  <path id="bottom-edge" d="{bot_edge}" fill="none" stroke="#b9b8bc" stroke-opacity="0.25" stroke-width="3"/>

  <!-- printed mark and microphone -->
  <g id="wordmarks"><path fill="#dedede" d="{ipaq}"/></g>
  <g id="mic">
    <ellipse cx="{f(CX + mx)}" cy="{my}" rx="{mrx}" ry="{mry}" fill="#050506"/>
    <path d="M{f(CX + mx - mrx * 0.3)},{my + mry - 2} A{mrx},{mry} 0 0 0 {f(CX + mx + mrx - 2)},{my + 4}" fill="none" stroke="#d0d0d0" stroke-opacity="0.7" stroke-width="3.5"/>
  </g>
</g>
</g>

<!-- glass slot in SVG units: a neutral placeholder until a screenshot is composited -->
<rect id="screen" x="{f(GLASS_U[0])}" y="{f(GLASS_U[1])}" width="{GLASS_U[2]}" height="{GLASS_U[3]}" fill="#c3c6c9"/>
<rect id="glass" x="{f(GLASS_U[0])}" y="{f(GLASS_U[1])}" width="{GLASS_U[2]}" height="{GLASS_U[3]}" fill="url(#hx-glass)" pointer-events="none"/>
</svg>
'''

    return build()


def build_hx2700(fonts):
    """Draw the hx2750/hx2790 from the hx2110 photograph and HP's hx2700 artwork."""
    # The hx2110 photograph shares the chassis; its vertical scale is 4% short
    # (camera tilt), which also brings the body to the published 76.6 x 119 mm.
    SX = 525 / 923
    SY = SX * 1.04
    GX, GY = 1018, 342.9                       # active glass, photo px
    CX = 1479.5                                # centre line, photo px

    def X(x):
        return 137.5 + (x - GX) * SX

    def Y(y):
        return 244.75 + (y - GY) * SY

    def pts(points):
        return [(X(x), Y(y)) for x, y in points]

    def sym(half):
        """Right-half (offset, y) list, top to bottom, as a closed photo-px outline."""
        return pts(mirror(half, CX))

    def ptxt(x, y):
        return f'{f(X(x))},{f(Y(y))}'

    BODY_HALF = [(0, 111), (280, 116), (380, 120), (480, 128), (540, 136), (575, 148), (600, 162),
                 (620, 190), (635, 240), (644, 300), (649, 420), (651, 1000), (651, 1700), (646, 1860),
                 (634, 1930), (616, 1975), (592, 2012), (556, 2045), (500, 2075), (420, 2093),
                 (250, 2101), (0, 2104)]
    FACE_HALF = [(0, 157), (440, 158), (500, 161), (535, 168), (560, 182), (577, 205), (588, 240),
                 (592, 300), (593, 600), (592, 1400), (588, 1650), (578, 1800), (570, 1880),
                 (558, 1930), (535, 1975), (505, 2015), (455, 2050), (380, 2075), (250, 2090), (0, 2095)]
    # Silver key bar: a smile-shaped top edge under the face plate, a deeper curve below.
    BAR_TOP = [(566, 1813), (500, 1822), (400, 1834), (300, 1840), (150, 1843), (0, 1844)]
    BAR_END = [(567, 1880), (556, 1922), (527, 1955)]
    BAR_BOT = [(480, 1972), (380, 1993), (280, 2007), (150, 2020), (0, 2025)]
    # Contacts/mail keys (mirrored): curved outer edge, sloping lower edge, d-pad side.
    KEY = [(402.5, 1841), (395, 1870), (380, 1898), (355, 1915), (325, 1922), (150, 1944), (150, 1843)]
    DPAD = dict(top=1840, bot=2048, ht=150, hb=128, rt=24, rb=40)
    ROCKER = dict(top=1862, bot=1990, ht=106, hb=88, rt=26, rb=30)
    SELECT = dict(top=1898, bot=1965, h=58, r=18, slot=(38, 1912, 1952, 10))
    WINDOW = (1003, 328, 1955, 1537)
    LEDS = (1140, 1192)                        # slit centres; the slits run 157-231
    BADGE = dict(x0=1400, x1=1556, y0=166, y1=262, r=12, disc=(1480, 216, 43))
    POWER = [(1752, 148), (1892, 148), (1880, 228), (1764, 228)]
    MIC = [(1744, 44), (1760, 58), (1776, 40)]
    SPEAKER = [(1722, 1820, 1986), (1750, 1818, 1990), (1778, 1828, 1984)]
    # hx2750/hx2790 only: recessed swipe channel, flush to the lower screen edge.
    RAMP = dict(top=1537, bot=1840, h=130)
    SENSOR = dict(y=1744, h=18, half=100)
    IPAQ = dict(x0=981, x1=1110, base=1612, cap=38)
    ICONS = [('calendar', 989, 1870, 58, 46), ('contacts', 1212, 1886, 56, 46),
             ('mail', 1750, 1882, 60, 42), ('itask', 1945, 1870, 40, 52)]

    body = spline(sym(BODY_HALF))
    face = spline(sym(FACE_HALF))
    left_side = lambda half: [(CX - h, y) for h, y in half]
    right_side = lambda half: [(CX + h, y) for h, y in half]
    bar_pts = (left_side(BAR_TOP) + right_side(BAR_TOP[::-1][1:]) + right_side(BAR_END)
               + right_side(BAR_BOT) + left_side(BAR_BOT[::-1][1:]) + left_side(BAR_END[::-1]))
    bar = spline(pts(bar_pts), tension=8)
    bar_top_edge = spline(pts(left_side(BAR_TOP) + right_side(BAR_TOP[::-1][1:])), closed=False, tension=8)
    bottom = [BAR_END[-1]] + BAR_BOT
    bar_bot_edge = spline(pts(left_side(bottom) + right_side(bottom[::-1][1:])), closed=False, tension=8)

    def key(side):
        outer = [(CX + side * h, y) for h, y in KEY[:5]]
        return (spline(pts(outer), closed=False, tension=8)
                + f' L{ptxt(CX + side * KEY[5][0], KEY[5][1])} L{ptxt(CX + side * KEY[6][0], KEY[6][1])} Z')

    def trapezoid(d, x_half_top, x_half_bot):
        return rounded(pts([(CX - x_half_top, d['top']), (CX + x_half_top, d['top']),
                            (CX + x_half_bot, d['bot']), (CX - x_half_bot, d['bot'])]),
                       [d['rt'] * SX, d['rt'] * SX, d['rb'] * SX, d['rb'] * SX])

    dpad = trapezoid(DPAD, DPAD['ht'], DPAD['hb'])
    rocker = trapezoid(ROCKER, ROCKER['ht'], ROCKER['hb'])
    s = SELECT
    select = (X(CX - s['h']), Y(s['top']), 2 * s['h'] * SX, (s['bot'] - s['top']) * SY, s['r'] * SX)
    sh, sy0, sy1, sr = s['slot']
    slot = (X(CX - sh), Y(sy0), 2 * sh * SX, (sy1 - sy0) * SY, sr * SX)

    # d-pad hit areas: the rocker split along the diagonals through the select key's corners
    rk = ROCKER
    r_tl, r_tr = (CX - rk['ht'], rk['top']), (CX + rk['ht'], rk['top'])
    r_bl, r_br = (CX - rk['hb'], rk['bot']), (CX + rk['hb'], rk['bot'])
    s_tl, s_tr = (CX - s['h'], s['top']), (CX + s['h'], s['top'])
    s_bl, s_br = (CX - s['h'], s['bot']), (CX + s['h'], s['bot'])
    def poly(*corners):
        return 'M' + ' L'.join(ptxt(*c) for c in corners) + ' Z'
    directions = (('up', 'Up', poly(r_tl, r_tr, s_tr, s_tl)), ('down', 'Down', poly(s_bl, s_br, r_br, r_bl)),
                  ('left', 'Left', poly(r_tl, s_tl, s_bl, r_bl)), ('right', 'Right', poly(s_tr, r_tr, r_br, s_br)))
    hits = ''.join(f'<path id="button-{n}" aria-label="{label}" d="{d}" fill="transparent" pointer-events="all"/>'
                   for n, label, d in directions)
    # Calendar and iTask are the bar's ends, beyond the outlined contacts and mail keys.
    def bar_end(side):
        edge = [(CX + side * h, y) for h, y in KEY[:5]]
        top = [(CX + side * h, y) for h, y in BAR_TOP[:2]]
        end = [(CX + side * h, y) for h, y in BAR_END + BAR_BOT[:2]]
        return poly(*top, *edge, (CX + side * 300, 2004), *end[::-1])
    ends = (f'<path id="button-calendar" aria-label="Calendar button" d="{bar_end(-1)}" fill="transparent" pointer-events="all"/>'
            f'<path id="button-itask" aria-label="iTask button" d="{bar_end(1)}" fill="transparent" pointer-events="all"/>')

    w0, w1 = (X(WINDOW[0]), Y(WINDOW[1])), (X(WINDOW[2]), Y(WINDOW[3]))
    g0, g1 = (137.5, 244.75), (662.5, 944.75)
    walls = (
        f'<polygon points="{f(w0[0])},{f(w0[1])} {f(w1[0])},{f(w0[1])} {f(g1[0])},{f(g0[1])} {f(g0[0])},{f(g0[1])}" fill="#2a2c30"/>'
        f'<polygon points="{f(w0[0])},{f(w1[1])} {f(w1[0])},{f(w1[1])} {f(g1[0])},{f(g1[1])} {f(g0[0])},{f(g1[1])}" fill="#3a3c41"/>'
        f'<polygon points="{f(w0[0])},{f(w0[1])} {f(g0[0])},{f(g0[1])} {f(g0[0])},{f(g1[1])} {f(w0[0])},{f(w1[1])}" fill="#1d1e21"/>'
        f'<polygon points="{f(w1[0])},{f(w0[1])} {f(g1[0])},{f(g0[1])} {f(g1[0])},{f(g1[1])} {f(w1[0])},{f(w1[1])}" fill="#26282b"/>')

    leds = ''
    for x, (n, label) in zip(LEDS, (('radio', 'Radio (Wi-Fi and Bluetooth)'),
                                    ('charge', 'Charge and notification'))):
        lx, ly, lw, lh = X(x - 7.5), Y(150), 15 * SX, (231 - 150) * SY
        leds += (f'<rect x="{f(lx - 1.2)}" y="{f(ly)}" width="{f(lw + 2.4)}" height="{f(lh + 1.2)}" rx="{f(lw / 2 + 1.2)}" fill="#08080a"/>'
                 f'<rect id="led-{n}" aria-label="{label} indicator" x="{f(lx)}" y="{f(ly)}" width="{f(lw)}" height="{f(lh)}" rx="{f(lw / 2)}" fill="#2a2a2f"/>'
                 f'<g pointer-events="none"><rect x="{f(lx)}" y="{f(ly)}" width="{f(lw)}" height="{f(lh)}" rx="{f(lw / 2)}" fill="url(#hx2-led)"/>'
                 f'<path d="M{f(lx + lw * 0.3)},{f(ly + lh * 0.5)} V{f(ly + lh - lw * 0.6)}" stroke="#fff" stroke-opacity="0.35" stroke-width="1.2" stroke-linecap="round"/></g>')

    b = BADGE
    bx0, by0, bx1, by1 = X(b['x0']), Y(b['y0']), X(b['x1']), Y(b['y1'])
    dcx, dcy, dr = b['disc']
    R = dr * SX
    badge = (f'<g id="badge">'
             f'<rect x="{f(bx0 - 1.5)}" y="{f(by0 - 1.5)}" width="{f(bx1 - bx0 + 3)}" height="{f(by1 - by0 + 3)}" rx="{f(b["r"] * SX + 1.5)}" fill="#0b0b0d"/>'
             f'<rect x="{f(bx0)}" y="{f(by0)}" width="{f(bx1 - bx0)}" height="{f(by1 - by0)}" rx="{f(b["r"] * SX)}" fill="url(#hx2-plate)"/>'
             f'<rect x="{f(bx0 + 1.2)}" y="{f(by0 + 1.2)}" width="{f(bx1 - bx0 - 2.4)}" height="{f(by1 - by0 - 2.4)}" rx="{f(b["r"] * SX - 1)}" fill="none" stroke="#fff" stroke-opacity="0.7" stroke-width="1.4"/>'
             f'<g transform="translate({f(X(dcx))},{f(Y(dcy))})"><circle r="{f(R)}" fill="url(#hx2-disc)"/>'
             f'<path d="{hp_monogram(R)}" fill="url(#hx2-letters)"/></g></g>')

    power = rounded(pts(POWER), [0, 0, 22 * SX, 22 * SX])
    pcx, pcy, pr = X(1822), Y(190), 7.5
    power_icon = (f'<path d="M{f(pcx - pr * 0.64)},{f(pcy - pr * 0.77)} A{f(pr)},{f(pr)} 0 1 0 {f(pcx + pr * 0.64)},{f(pcy - pr * 0.77)}'
                  f' M{f(pcx)},{f(pcy - pr * 1.15)} V{f(pcy - pr * 0.1)}" fill="none" stroke="#6b6866" stroke-width="1.6" stroke-linecap="round"/>')

    mic = ''.join(f'<rect x="{f(X(1092 - w / 2))}" y="{f(Y(y - 4.5))}" width="{f(w * SX)}" height="{f(9 * SY)}" rx="{f(4.5 * SY)}" fill="#101113"/>'
                  for y, w in MIC)
    speaker = ''.join(
        f'<path d="M{ptxt(x0, y)} Q{ptxt((x0 + x1) / 2, y - 8)} {ptxt(x1, y)} Q{ptxt((x0 + x1) / 2, y + 8)} {ptxt(x0, y)} Z" fill="#101113"/>'
        f'<path d="M{ptxt(x0 + 20, y + 5)} Q{ptxt((x0 + x1) / 2, y + 9)} {ptxt(x1 - 20, y + 5)}" fill="none" stroke="#c4cad2" stroke-opacity="0.45" stroke-width="1"/>'
        for y, x0, x1 in SPEAKER)

    rp = RAMP
    ramp = (
        f"M{ptxt(CX - rp['h'], rp['top'])} L{ptxt(CX + rp['h'], rp['top'])} "
        f"C{ptxt(CX + 126, 1560)} {ptxt(CX + 122, 1580)} {ptxt(CX + 120, 1610)} "
        f"L{ptxt(CX + 108, 1786)} Q{ptxt(CX + 106, 1832)} {ptxt(CX + 92, rp['bot'])} "
        f"L{ptxt(CX - 92, rp['bot'])} Q{ptxt(CX - 106, 1832)} {ptxt(CX - 108, 1786)} "
        f"L{ptxt(CX - 120, 1610)} C{ptxt(CX - 122, 1580)} {ptxt(CX - 126, 1560)} "
        f"{ptxt(CX - rp['h'], rp['top'])} Z"
    )
    inset = (
        f"M{ptxt(CX - 93, 1557)} Q{ptxt(CX - 99, 1560)} {ptxt(CX - 99, 1575)} "
        f"L{ptxt(CX - 87, 1775)} Q{ptxt(CX - 85, 1802)} {ptxt(CX - 72, 1812)} "
        f"L{ptxt(CX + 72, 1812)} Q{ptxt(CX + 85, 1802)} {ptxt(CX + 87, 1775)} "
        f"L{ptxt(CX + 99, 1575)} Q{ptxt(CX + 99, 1560)} {ptxt(CX + 93, 1557)} Z"
    )
    se = SENSOR
    sx0, sy0 = X(CX - se['half']), Y(se['y'] - se['h'] / 2)
    sw, sh2 = 2 * se['half'] * SX, se['h'] * SY
    sensor = (f'<g id="fingerprint-reader" aria-label="Fingerprint reader">'
              f'<rect x="{f(sx0)}" y="{f(sy0)}" width="{f(sw)}" height="{f(sh2)}" rx="{f(sh2 / 2)}" fill="#121315"/>'
              f'<rect id="fingerprint-sensor" x="{f(sx0 + 4)}" y="{f(sy0 + sh2 * 0.32)}" width="{f(sw - 8)}" height="{f(sh2 * 0.36)}" rx="{f(sh2 * 0.18)}" fill="#292b2d"/>'
              f'<path d="M{f(sx0 + 4)},{f(sy0 + sh2 - 0.5)} H{f(sx0 + sw - 4)}" stroke="#9a9da0" stroke-opacity="0.65" stroke-width="0.8"/></g>')

    def icon(kind, x, y, w, h):
        w, h = w * SX, h * SY
        if kind == 'calendar':
            cells = ''.join(f'<rect x="{f(-w / 2 + i * w / 4)}" y="{f(-h / 2 + j * h / 3)}" width="{f(w / 4)}" height="{f(h / 3)}"/>'
                            for i in range(4) for j in range(3))
            fills = ''.join(f'<rect x="{f(-w / 2 + i * w / 4)}" y="{f(-h / 2)}" width="{f(w / 4)}" height="{f(h / 3)}" stroke="none" fill="#33343b"/>'
                            for i in (1, 3))
            return cells + fills
        if kind == 'contacts':
            return (f'<rect x="{f(-w / 2)}" y="{f(-h / 2)}" width="{f(w)}" height="{f(h)}"/>'
                    f'<path d="M{f(-w * 0.06)},{f(-h / 2)} V{f(h / 2)}"/>'
                    f'<rect x="{f(-w * 0.4)}" y="{f(-h * 0.32)}" width="{f(w * 0.22)}" height="{f(h * 0.26)}" fill="#33343b" stroke="none"/>'
                    + ''.join(f'<path d="M{f(w * 0.08)},{f(-h * 0.28 + i * h * 0.19)} H{f(w * 0.4)}"/>' for i in range(4)))
        if kind == 'mail':
            return (f'<rect x="{f(-w / 2)}" y="{f(-h / 2)}" width="{f(w)}" height="{f(h)}"/>'
                    f'<path d="M{f(-w / 2)},{f(-h / 2)} L0,{f(h * 0.12)} L{f(w / 2)},{f(-h / 2)}'
                    f' M{f(-w / 2)},{f(h / 2)} L{f(-w * 0.12)},{f(-h * 0.04)} M{f(w / 2)},{f(h / 2)} L{f(w * 0.12)},{f(-h * 0.04)}" stroke-linejoin="round"/>')
        # iTask: a C-shaped arrow ending in a head pointing up and right
        return (f'<path d="M{f(w * 0.05)},{f(h * 0.42)} C{f(-w * 0.55)},{f(h * 0.45)} {f(-w * 0.5)},{f(-h * 0.2)} {f(w * 0.05)},{f(-h * 0.3)}" stroke-width="2.4" stroke-linecap="round"/>'
                f'<path d="M{f(-w * 0.05)},{f(-h * 0.42)} L{f(w * 0.5)},{f(-h * 0.5)} L{f(w * 0.18)},{f(-h * 0.08)} Z" fill="#33343b" stroke="none"/>')
    icons = ''.join(f'<g transform="translate({f(X(x))},{f(Y(y))})" fill="none" stroke="#33343b" stroke-width="1.5">{icon(k, x, y, w, h)}</g>'
                    for k, x, y, w, h in ICONS)

    ipaq = fonts.word_path('iPAQ', 'OpenSans_Bold.ttf', IPAQ['cap'] * SY, X(IPAQ['x0']), Y(IPAQ['base']), 'start',
                           (IPAQ['x1'] - IPAQ['x0']) * SX)
    left, right = X(CX - 660), X(CX + 660)

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 72 800 1250">
<!--
  HP iPAQ hx2750/hx2790/hx2795, front view. Glass: <rect id="screen"> x=137.5 y=244.75 width=525 height=700 (3:4, 240x320 px at 2.1875 units per pixel).

  SPDX-FileCopyrightText: 2026 Koen Kooi
  SPDX-License-Identifier: CC-BY-SA-4.0

  Provenance: an original vector drawing, written as SVG geometry and
  gradients and drawn with the assistance of Claude from reference
  photographs: "HP iPAQ hx2110, front view.jpg" by Yuri Litvinenko
  (CC BY 2.0, Wikimedia Commons), which shares the hx2700 chassis, and the
  hx2700 illustrations in the HP iPAQ hx2000 Series User's Guide for the
  fingerprint reader. No third-party artwork was traced or embedded. The
  printed "iPAQ" is glyph outlines from the Open Sans font (SIL Open Font
  License); the hp badge is drawn from simple shapes. "HP", "hp" and "iPAQ"
  are trademarks of their owners and appear only to identify the device.
-->
<defs>
  <linearGradient id="hx2-rim" gradientUnits="userSpaceOnUse" x1="{f(left)}" y1="0" x2="{f(right)}" y2="0">
    <stop offset="0" stop-color="#55565b"/><stop offset="0.02" stop-color="#2a2a2e"/><stop offset="0.06" stop-color="#151518"/>
    <stop offset="0.94" stop-color="#141417"/><stop offset="0.975" stop-color="#2e2f33"/><stop offset="1" stop-color="#4a4b50"/>
  </linearGradient>
  <linearGradient id="hx2-rim-v" gradientUnits="userSpaceOnUse" x1="0" y1="{f(Y(111))}" x2="0" y2="{f(Y(2104))}">
    <stop offset="0" stop-color="#fff" stop-opacity="0.16"/><stop offset="0.03" stop-color="#fff" stop-opacity="0"/>
    <stop offset="0.97" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity="0.3"/>
  </linearGradient>
  <linearGradient id="hx2-face" gradientUnits="userSpaceOnUse" x1="0" y1="{f(Y(157))}" x2="0" y2="{f(Y(1840))}">
    <stop offset="0" stop-color="#6f747b"/><stop offset="0.3" stop-color="#757a81"/><stop offset="1" stop-color="#787d85"/>
  </linearGradient>
  <linearGradient id="hx2-face-h" gradientUnits="userSpaceOnUse" x1="{f(X(CX - 593))}" y1="0" x2="{f(X(CX + 593))}" y2="0">
    <stop offset="0" stop-color="#fff" stop-opacity="0.1"/><stop offset="0.06" stop-color="#fff" stop-opacity="0"/>
    <stop offset="0.94" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity="0.12"/>
  </linearGradient>
  <linearGradient id="hx2-bar" gradientUnits="userSpaceOnUse" x1="0" y1="{f(Y(1813))}" x2="0" y2="{f(Y(2025))}">
    <stop offset="0" stop-color="#d7dae1"/><stop offset="0.35" stop-color="#e3e5eb"/><stop offset="1" stop-color="#c9ccd3"/>
  </linearGradient>
  <linearGradient id="hx2-key" gradientUnits="userSpaceOnUse" x1="0" y1="{f(Y(1841))}" x2="0" y2="{f(Y(1944))}">
    <stop offset="0" stop-color="#c6cad1"/><stop offset="1" stop-color="#d9dce2"/>
  </linearGradient>
  <linearGradient id="hx2-bumper" gradientUnits="userSpaceOnUse" x1="0" y1="{f(Y(1960))}" x2="0" y2="{f(Y(2100))}">
    <stop offset="0" stop-color="#46484c"/><stop offset="0.5" stop-color="#36383b"/><stop offset="1" stop-color="#232427"/>
  </linearGradient>
  <linearGradient id="hx2-chrome" gradientUnits="userSpaceOnUse" x1="{f(X(CX - 150))}" y1="0" x2="{f(X(CX + 150))}" y2="0">
    <stop offset="0" stop-color="#e9eaee"/><stop offset="0.08" stop-color="#4a474f"/><stop offset="0.16" stop-color="#2c2a31"/>
    <stop offset="0.5" stop-color="#5f5d64"/><stop offset="0.84" stop-color="#2c2a31"/><stop offset="0.92" stop-color="#55525a"/><stop offset="1" stop-color="#e4e5e9"/>
  </linearGradient>
  <linearGradient id="hx2-chrome-v" gradientUnits="userSpaceOnUse" x1="0" y1="{f(Y(DPAD['top']))}" x2="0" y2="{f(Y(DPAD['bot']))}">
    <stop offset="0" stop-color="#fff" stop-opacity="0.55"/><stop offset="0.06" stop-color="#fff" stop-opacity="0"/>
    <stop offset="0.7" stop-color="#fff" stop-opacity="0.1"/><stop offset="0.78" stop-color="#fff" stop-opacity="0.6"/>
    <stop offset="0.87" stop-color="#fff" stop-opacity="0.45"/><stop offset="0.91" stop-color="#000" stop-opacity="0.45"/>
    <stop offset="0.96" stop-color="#fff" stop-opacity="0.7"/><stop offset="1" stop-color="#000" stop-opacity="0.2"/>
  </linearGradient>
  <linearGradient id="hx2-rocker" gradientUnits="userSpaceOnUse" x1="0" y1="{f(Y(ROCKER['top']))}" x2="0" y2="{f(Y(ROCKER['bot']))}">
    <stop offset="0" stop-color="#9da1a8"/><stop offset="0.12" stop-color="#c6c8d0"/><stop offset="0.8" stop-color="#bfc2ca"/><stop offset="1" stop-color="#dfe1e6"/>
  </linearGradient>
  <linearGradient id="hx2-select" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#f2f3f5"/><stop offset="0.45" stop-color="#8b8990"/><stop offset="0.55" stop-color="#57555c"/><stop offset="1" stop-color="#e6e7ea"/>
  </linearGradient>
  <linearGradient id="hx2-slot" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#2a2830"/><stop offset="0.6" stop-color="#4a4756"/><stop offset="1" stop-color="#8e8c98"/>
  </linearGradient>
  <linearGradient id="hx2-power" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#1c1a1a"/><stop offset="0.7" stop-color="#2f2c2b"/><stop offset="0.86" stop-color="#5d5a58"/><stop offset="0.93" stop-color="#e9e9ef"/><stop offset="1" stop-color="#6b6a70"/>
  </linearGradient>
  <linearGradient id="hx2-ramp" gradientUnits="userSpaceOnUse" x1="{f(X(CX - RAMP['h']))}" y1="0" x2="{f(X(CX + RAMP['h']))}" y2="0">
    <stop offset="0" stop-color="#858788"/><stop offset="0.08" stop-color="#5a5d5f"/><stop offset="0.5" stop-color="#56595b"/>
    <stop offset="0.92" stop-color="#5e6163"/><stop offset="1" stop-color="#858788"/>
  </linearGradient>
  <linearGradient id="hx2-ramp-v" gradientUnits="userSpaceOnUse" x1="0" y1="{f(Y(RAMP['top']))}" x2="0" y2="{f(Y(RAMP['bot']))}">
    <stop offset="0" stop-color="#17191b" stop-opacity="0.46"/><stop offset="0.18" stop-color="#000" stop-opacity="0.04"/>
    <stop offset="0.7" stop-color="#fff" stop-opacity="0.1"/><stop offset="0.96" stop-color="#fff" stop-opacity="0.4"/>
    <stop offset="1" stop-color="#17191b" stop-opacity="0.5"/>
  </linearGradient>
  <linearGradient id="hx2-ramp-inset" gradientUnits="userSpaceOnUse" x1="0" y1="{f(Y(1557))}" x2="0" y2="{f(Y(1812))}">
    <stop offset="0" stop-color="#292c2e" stop-opacity="0.34"/><stop offset="0.56" stop-color="#626567" stop-opacity="0.38"/>
    <stop offset="1" stop-color="#c1c3c4" stop-opacity="0.38"/>
  </linearGradient>
  <linearGradient id="hx2-led" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#000" stop-opacity="0.35"/><stop offset="0.45" stop-color="#fff" stop-opacity="0.12"/><stop offset="1" stop-color="#000" stop-opacity="0.4"/>
  </linearGradient>
  <linearGradient id="hx2-plate" x1="0" y1="0" x2="0.35" y2="1">
    <stop offset="0" stop-color="#e9eaea"/><stop offset="0.35" stop-color="#bfc0c0"/>
    <stop offset="0.7" stop-color="#a9aaab"/><stop offset="1" stop-color="#d6d7d7"/>
  </linearGradient>
  <radialGradient id="hx2-disc" cx="0.5" cy="0.5" r="0.5" fx="0.42" fy="0.38">
    <stop offset="0" stop-color="#3a3540"/><stop offset="0.8" stop-color="#1b181d"/><stop offset="1" stop-color="#110f12"/>
  </radialGradient>
  <linearGradient id="hx2-letters" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#fafafa"/><stop offset="1" stop-color="#c4c6c8"/>
  </linearGradient>
  <linearGradient id="hx2-glass" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#fff" stop-opacity="0.06"/><stop offset="0.45" stop-color="#fff" stop-opacity="0.012"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
  </linearGradient>
  <filter id="hx2-shadow" x="-15%" y="-10%" width="130%" height="125%">
    <feGaussianBlur in="SourceAlpha" stdDeviation="7"/><feOffset dy="6" result="b"/>
    <feFlood flood-color="#000" flood-opacity="0.35"/><feComposite in2="b" operator="in"/>
  </filter>
  <filter id="hx2-grain" x="0" y="0" width="1" height="1">
    <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="27" result="n"/>
    <feColorMatrix in="n" type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  4.2 0 0 0 -2.05" result="light"/>
    <feColorMatrix in="n" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  -3.4 0 0 0 1.5" result="dark"/>
    <feMerge><feMergeNode in="dark"/><feMergeNode in="light"/></feMerge>
  </filter>
  <filter id="hx2-soft" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="2.5"/></filter>
  <clipPath id="hx2-body-clip"><path d="{body}"/></clipPath>
  <clipPath id="hx2-face-clip"><path d="{face}"/></clipPath>
  <clipPath id="hx2-bar-clip"><path d="{bar}"/></clipPath>
  <clipPath id="hx2-dpad-clip"><path d="{dpad}"/></clipPath>
  <clipPath id="hx2-rocker-clip"><path d="{rocker}"/></clipPath>
</defs>

<g id="shadow" fill="#000" filter="url(#hx2-shadow)"><path d="{body}"/></g>
<g id="device">
  <!-- black rubber rim around the charcoal face plate -->
  <path id="body-edge" d="{body}" fill="url(#hx2-rim)"/>
  <path d="{body}" fill="url(#hx2-rim-v)"/>
  <path d="{body}" fill="none" stroke="#000" stroke-opacity="0.6" stroke-width="1"/>
  <g id="face">
    <path id="face-base" d="{face}" fill="url(#hx2-face)"/>
    <g clip-path="url(#hx2-face-clip)">
      <path d="{face}" fill="url(#hx2-face-h)"/>
      <rect x="{f(X(CX - 600))}" y="{f(Y(150))}" width="{f(1200 * SX)}" height="{f(1960 * SY)}" filter="url(#hx2-grain)" opacity="0.22"/>
      <!-- lower bumper below the key bar -->
      <rect x="{f(X(CX - 600))}" y="{f(Y(1900))}" width="{f(1200 * SX)}" height="{f(220 * SY)}" fill="url(#hx2-bumper)"/>
    </g>
    <path d="{face}" fill="none" stroke="#000" stroke-opacity="0.55" stroke-width="1.2"/>
    <path d="M{ptxt(CX - 440, 158.5)} H{f(X(CX + 440))}" stroke="#fff" stroke-opacity="0.22" stroke-width="1"/>
  </g>

  <g id="leds">{leds}</g>
  {badge}
  <g id="button-power" aria-label="Power button">
    <path d="{power}" fill="#121214"/>
    <path d="{rounded(pts([(1758, 148), (1886, 148), (1875, 225), (1769, 225)]), [0, 0, 19 * SX, 19 * SX])}" fill="url(#hx2-power)"/>
    {power_icon}
  </g>

  <!-- recessed screen: lit top wall, black border, glass -->
  <g id="frame">
    <path d="M{ptxt(WINDOW[0] - 4, WINDOW[1] - 22)} H{f(X(WINDOW[2] + 4))} L{ptxt(WINDOW[2], WINDOW[1])} H{f(w0[0])} Z" fill="#8d9197"/>
    <path d="M{ptxt(WINDOW[0] - 4, WINDOW[1] - 22)} H{f(X(WINDOW[2] + 4))}" stroke="#d4d7dc" stroke-opacity="0.7" stroke-width="1.2"/>
    <rect x="{f(w0[0])}" y="{f(w0[1])}" width="{f(w1[0] - w0[0])}" height="{f(w1[1] - w0[1])}" fill="#0e0f11"/>
    {walls}
    <path d="M{f(w0[0])},{f(w1[1] + 0.8)} H{f(w1[0])}" stroke="#a4a8ae" stroke-opacity="0.6" stroke-width="1.2"/>
  </g>

  <!-- hx2750/hx2790 recessed swipe channel with the fingerprint sensor -->
  <g id="ramp">
    <path d="{ramp}" fill="#000" fill-opacity="0.35" filter="url(#hx2-soft)" transform="translate(1.5 2)"/>
    <path d="{ramp}" fill="url(#hx2-ramp)"/>
    <path d="{ramp}" fill="url(#hx2-ramp-v)"/>
    <path d="{ramp}" fill="none" stroke="#25282a" stroke-opacity="0.78" stroke-width="1.1"/>
    <path d="{inset}" fill="url(#hx2-ramp-inset)" stroke="#85888a" stroke-opacity="0.48" stroke-width="0.8"/>
    <path d="M{ptxt(CX - 116, 1570)} C{ptxt(CX - 111, 1650)} {ptxt(CX - 108, 1730)} {ptxt(CX - 103, 1790)}"
          fill="none" stroke="#d0d1d2" stroke-opacity="0.62" stroke-width="2"/>
    <path d="M{ptxt(CX + 116, 1570)} C{ptxt(CX + 111, 1650)} {ptxt(CX + 108, 1730)} {ptxt(CX + 103, 1790)}"
          fill="none" stroke="#202325" stroke-opacity="0.68" stroke-width="1.6"/>
    <path d="M{ptxt(CX - 72, 1808)} Q{ptxt(CX, 1830)} {ptxt(CX + 72, 1808)}"
          fill="none" stroke="#d1d2d3" stroke-opacity="0.55" stroke-width="1.8"/>
    {sensor}
  </g>

  <!-- silver key bar, lower bumper and d-pad -->
  <g id="keys">
    <path d="{bar}" fill="url(#hx2-bar)"/>
    <rect clip-path="url(#hx2-bar-clip)" x="{f(X(CX - 600))}" y="{f(Y(1800))}" width="{f(1200 * SX)}" height="{f(240 * SY)}" filter="url(#hx2-grain)" opacity="0.3"/>
    <path d="{bar_top_edge}" fill="none" stroke="#2f323a" stroke-width="1.6"/>
    <path d="{bar_bot_edge}" fill="none" stroke="#2a2c33" stroke-width="1.4"/>
    <path id="button-contacts" aria-label="Contacts button" d="{key(-1)}" fill="url(#hx2-key)" stroke="#4d505b" stroke-width="1.1"/>
    <path id="button-mail" aria-label="Messaging button" d="{key(1)}" fill="url(#hx2-key)" stroke="#4d505b" stroke-width="1.1"/>
    <g id="app-glyphs">{icons}</g>
    {ends}
    <path d="{dpad}" fill="url(#hx2-chrome)"/>
    <path d="{dpad}" fill="url(#hx2-chrome-v)"/>
    <path d="{dpad}" fill="none" stroke="#0d0d10" stroke-width="1.2"/>
    <path id="rocker" d="{rocker}" fill="url(#hx2-rocker)"/>
    <rect clip-path="url(#hx2-rocker-clip)" x="{f(X(CX - 120))}" y="{f(Y(ROCKER['top']))}" width="{f(240 * SX)}" height="{f(140 * SY)}" filter="url(#hx2-grain)" opacity="0.3"/>
    <g clip-path="url(#hx2-dpad-clip)"><path d="{rocker}" fill="none" stroke="#000" stroke-opacity="0.4" stroke-width="3" filter="url(#hx2-soft)"/></g>
    <path d="{rocker}" fill="none" stroke="#f6f7f8" stroke-opacity="0.8" stroke-width="1"/>
    <rect id="button-select" aria-label="Select button" x="{f(select[0])}" y="{f(select[1])}" width="{f(select[2])}" height="{f(select[3])}" rx="{f(select[4])}" fill="url(#hx2-select)" stroke="#3a383f" stroke-width="0.8"/>
    <rect x="{f(slot[0])}" y="{f(slot[1])}" width="{f(slot[2])}" height="{f(slot[3])}" rx="{f(slot[4])}" fill="url(#hx2-slot)" pointer-events="none"/>
    <path d="M{f(slot[0] + 3)},{f(slot[1] + 2)} H{f(slot[0] + slot[2] - 3)}" stroke="#fff" stroke-opacity="0.7" stroke-width="1" pointer-events="none"/>
    {hits}
  </g>

  <g id="mic">{mic}</g>
  <g id="speaker">{speaker}</g>
  <g id="wordmarks"><path fill="#a6adb4" d="{ipaq}"/></g>
</g>

<!-- glass slot in SVG units: a neutral placeholder until a screenshot is composited -->
<rect id="screen" x="137.5" y="244.75" width="525" height="700" fill="#c3c6c9"/>
<rect id="glass" x="137.5" y="244.75" width="525" height="700" fill="url(#hx2-glass)" pointer-events="none"/>
</svg>
'''


def sliding_parts(fonts):
    """Shared shell, controls and US keyboard for Collie and Poodle."""
    f = fmt3
    text_path = fonts.text_path

    def row_y(x, row):
        return 1013 + 0.00038 * (x - 408) ** 2 + 55 * row


    def key(key_id, label, x, y, *, kind="light", width=43, icon=None):
        height = 40 if kind == "light" else 37
        rim = "#070809" if kind == "light" else "#0a0c12"
        fill = "url(#key-light)" if kind == "light" else "url(#key-blue)"
        stroke = "#777b7b" if kind == "light" else "#344373"
        legend = "#25292a" if kind == "light" else "#eff2ff"
        title = escape(label or icon or key_id)
        result = [
            f'<g id="key-{key_id}" aria-label="{title}" transform="translate({f(x)} {f(y)})">',
            f'<ellipse cy="2" rx="{f(width/2+3)}" ry="{f(height/2+3)}" fill="{rim}" opacity=".9"/>',
        ]
        if key_id == "fn":
            result.append(f'<ellipse rx="{f(width/2+5)}" ry="{f(height/2+5)}" fill="none" stroke="#bca848" stroke-width="2"/>')
        result.extend([
            f'<rect x="{f(-width/2)}" y="{f(-height/2)}" width="{f(width)}" height="{height}" rx="{f(height/2)}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>',
            f'<path d="M{f(-width/2+8)} -9 Q0 -{f(height/2+3)} {f(width/2-8)} -9" fill="none" stroke="#fff" stroke-opacity=".4" stroke-width="1.4"/>',
        ])
        if icon == "shift":
            result.append('<path d="M-10 2 L0 -9 10 2 6 2 6 9 -6 9 -6 2 Z" fill="none" stroke="#333638" stroke-width="2.6" stroke-linejoin="round"/>')
        elif icon == "backspace":
            result.append('<path d="M-10 0 L-2 -6 V-3 H9 V3 H-2 V6 Z" fill="#303335"/>')
        elif icon == "enter":
            result.append('<path d="M9 -7 V1 Q9 4 6 4 H-5 M-10 4 L-3 -1 V9 Z" fill="none" stroke="#f3f5ff" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round"/>')
        elif label:
            cap = 19 if len(label) == 1 else (13 if label == "Space" else 14)
            result.append(text_path(label, 0, cap * .36, cap, face="bold" if len(label) == 1 else "regular", fill=legend))
        result.append("</g>")
        return "\n".join(result)


    def keyboard():
        parts = ['''<g id="keyboard">
<path d="M59 945 Q400 865 741 945 L741 1324 Q400 1232 59 1324 Z" fill="url(#keyboard-bed)" stroke="#242526" stroke-width="3"/>
<path d="M64 966 V1314 M736 966 V1314" stroke="#929596" stroke-width="5" opacity=".65"/>
<path d="M70 979 Q400 903 730 979 M70 1307 Q400 1221 730 1307" fill="none" stroke="#929899" stroke-opacity=".23" stroke-width="3"/>''']
        xs = [138 + 60.5 * i for i in range(10)]
        for i, char in enumerate("QWERTYUIOP"):
            x, y = xs[i], row_y(xs[i], 0)
            parts.append(key(char.lower(), char, x, y))
            parts.append(text_path(str((i + 1) % 10), x, y - 28, 10.5, face="bold", fill="#b5a15b"))

        for i, char in enumerate("ASDFGHJKL"):
            x, y = xs[i] + 5, row_y(xs[i], 1)
            parts.append(key(char.lower(), char, x, y))
        parts.append(key("backspace", "", xs[9] + 5, row_y(xs[9], 1), icon="backspace"))
        for i, alt in enumerate(["!", "@", "#", "$", "%", "_", "&", "*", "(", "Del"]):
            x, y = xs[i] + 5, row_y(xs[i], 1)
            parts.append(text_path(alt, x, y - 26, 10.5, face="bold", fill="#d3ba52"))

        parts.append(key("shift-left", "", xs[0], row_y(xs[0], 2), icon="shift"))
        for i, char in enumerate("ZXCVBNM", 1):
            x, y = xs[i], row_y(xs[i], 2)
            parts.append(key(char.lower(), char, x, y))
        parts.append(key("comma-semicolon", ",;", xs[8], row_y(xs[8], 2)))
        parts.append(key("shift-right", "", xs[9], row_y(xs[9], 2), icon="shift"))
        for i, alt in [(2, "Cut"), (3, "Copy"), (4, "Paste"), (5, "-"), (6, "+"), (7, "="), (8, ")")]:
            x, y = xs[i], row_y(xs[i], 2)
            parts.append(text_path(alt, x, y - 27, 9.5, face="bold", fill="#d3ba52"))

        bottom = [
            ("fn", "Fn", 148, 1221, 53, "blue", None, ""),
            ("tab", "Tab", 222, 1207, 56, "blue", None, "Caps"),
            ("slash", "/?", 297, 1198, 58, "blue", None, "Num"),
            ("space", "Space", 411, 1189, 137, "light", None, "Symbol"),
            ("quote", "`\"", 532, 1197, 57, "blue", None, "~"),
            ("period", ".:", 607, 1208, 57, "blue", None, "&lt;"),
            ("enter", "", 681, 1221, 57, "blue", "enter", "&gt;"),
        ]
        for key_id, label, x, y, width, kind, icon, alt in bottom:
            parts.append(key(key_id, label, x, y, width=width, kind=kind, icon=icon))
            if alt:
                parts.append(text_path({"&lt;": "<", "&gt;": ">"}.get(alt, alt), x, y - 25, 10, face="bold", fill="#d3ba52"))
        parts.append("</g>")
        return "\n".join(parts)


    def embossed_band():
        letters = "Personal Mobile Tool"
        spacing = 19.3
        first = 400 - (len(letters) - 1) * spacing / 2
        result = ['<g aria-label="Personal Mobile Tool">']
        for i, char in enumerate(letters):
            if char == " ":
                continue
            x = first + i * spacing
            y = 997 + 0.00033 * (x - 400) ** 2
            angle = math.degrees(math.atan(0.00066 * (x - 400)))
            result.append(f'<g transform="rotate({f(angle)} {f(x)} {f(y)})">')
            result.append(text_path(char, x + .7, y + 1.4, 15, fill="#fff", extra='opacity=".7"'))
            result.append(text_path(char, x, y, 15, fill="#6d7372", extra='opacity=".72"'))
            result.append("</g>")
        return "\n".join(result + ["</g>"])


    def app_button(name, x, y, icon):
        return f'''<g id="button-{name}" aria-label="{name} button" transform="translate({x} {y})">
<circle r="33" fill="url(#button-rim)" stroke="#55595a" stroke-width="2"/>
<circle cy="-1" r="27.5" fill="url(#button-face)" stroke="#666b6b" stroke-width="1.3"/>
<path d="M-20 -17 Q0 -29 20 -17" fill="none" stroke="#fff" stroke-opacity=".58" stroke-width="2"/>
<g fill="none" stroke="#454a4a" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">{icon}</g>
</g>'''


    ICONS = {
        "calendar": '<path d="M-15 -8 L8 -8 8 10 -15 10 Z M-10 -12 H13 V6 M-6 -3 L-2 -6 V6 M-6 6 H2"/>',
        "contacts": '<ellipse cx="0" cy="-6" rx="5.5" ry="7"/><path d="M-16 12 Q-12 3 -5 3 Q0 8 5 3 Q13 4 16 12"/>',
        "menu": '<path d="M-14 -12 H10 V12 H-14 Z M-9 -6 H4 M-9 0 H4 M-9 6 H4 M14 -7 V9 M10 5 L14 10 18 5"/>',
        "mail": '<rect x="-15" y="-9" width="30" height="19" rx="1"/><path d="M-15 -8 L0 2 15 -8"/>',
    }


    def slider():
        parts = ['''<g id="slider">
<path d="M47 1002 Q400 920 753 1002 L753 1356 Q752 1379 729 1382 Q400 1394 71 1382 Q48 1380 47 1356 Z" fill="#292b2d" stroke="#18191a" stroke-width="3" filter="url(#shadow)" opacity=".4"/>
<path d="M50 1002 Q400 920 750 1002 L750 1353 Q750 1375 728 1377 Q400 1387 72 1377 Q50 1375 50 1353 Z" fill="url(#control-face)" stroke="#636667" stroke-width="2"/>
<path d="M53 1008 Q400 926 747 1008 L747 1352 Q747 1371 727 1373 Q400 1383 73 1373 Q53 1371 53 1352 Z" fill="url(#control-sheen)"/>
<path d="M50 1003 Q400 921 750 1003 L750 1061 Q400 979 50 1061 Z" fill="url(#ribbon)" stroke="#777b7b" stroke-width="2"/>
<path d="M53 1008 Q400 927 747 1008 M52 1058 Q400 976 748 1058" fill="none" stroke="#fff" stroke-opacity=".65" stroke-width="2"/>
<path d="M50 1062 Q400 980 750 1062" fill="none" stroke="#525657" stroke-width="3" opacity=".75"/>''', embossed_band()]
        parts.append('''<g id="button-home" aria-label="Home button">
<path d="M342 1038 Q400 1032 458 1038 Q462 1039 462 1044 V1105 Q460 1113 452 1110 Q400 1083 348 1110 Q338 1113 338 1105 V1044 Q338 1039 342 1038 Z" fill="url(#home-face)" stroke="#55595a" stroke-width="3"/>
<path d="M343 1041 Q400 1036 457 1041" fill="none" stroke="#fff" stroke-opacity=".55" stroke-width="2"/>
<g fill="none" stroke="#4b5050" stroke-width="3.3" stroke-linecap="round" stroke-linejoin="round"><path d="M382 1070 L400 1054 418 1070 M385 1068 V1082 H415 V1068 M396 1082 V1073 H405 V1082"/><path d="M410 1057 V1052 H416 V1064"/></g>
</g>''')
        for name, x, y in [("calendar", 151, 1117), ("contacts", 250, 1104), ("menu", 550, 1104), ("mail", 649, 1117)]:
            parts.append(app_button(name, x, y, ICONS[name]))
        parts.append('''<g id="mark-backlight" aria-label="Backlight symbol" transform="translate(587 1152)" fill="none" stroke="#555b5a" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" opacity=".85" pointer-events="none">
<path d="M-2 12 Q-3 8 -6 4 A9 9 0 1 1 6 4 Q3 8 2 12 Z M-3 15 H3 M-2 18 H2 M-12 -9 L-15 -12 M12 -9 L15 -12 M0 -13 V-17"/>
</g>
<g id="button-cancel" aria-label="Cancel / power button" transform="translate(216 1214)">
<path d="M-62 -15 Q-73 -24 -52 -28 Q-8 -36 48 -34 Q58 -33 58 -23 L59 42 Q58 51 46 46 Q-12 23 -62 -15 Z" fill="url(#triangle-edge)" stroke="#555a5a" stroke-width="2.5"/>
<path d="M-57 -15 Q-64 -21 -50 -24 Q-6 -31 45 -29 Q53 -29 53 -20 L54 35 Q53 41 45 38 Q-15 17 -57 -15 Z" fill="url(#triangle-face)"/>
<path d="M-52 -21 Q-3 -31 46 -27" fill="none" stroke="#fff" stroke-opacity=".65" stroke-width="2"/>''')
        parts.append(text_path("Cancel", 12, 0, 15, fill="#454949"))
        parts.append("</g>")
        parts.append('''<g id="button-ok" aria-label="OK button" transform="translate(584 1214)">
<path d="M62 -15 Q73 -24 52 -28 Q8 -36 -48 -34 Q-58 -33 -58 -23 L-59 42 Q-58 51 -46 46 Q12 23 62 -15 Z" fill="url(#triangle-edge)" stroke="#555a5a" stroke-width="2.5"/>
<path d="M57 -15 Q64 -21 50 -24 Q6 -31 -45 -29 Q-53 -29 -53 -20 L-54 35 Q-53 41 -45 38 Q15 17 57 -15 Z" fill="url(#triangle-face)"/>
<path d="M52 -21 Q3 -31 -46 -27" fill="none" stroke="#fff" stroke-opacity=".65" stroke-width="2"/>''')
        parts.append(text_path("OK", -7, 1, 16, fill="#454949"))
        parts.append("</g>")
        parts.append(text_path("On/Off", 179, 1305, 14, fill="#5c6160", extra='opacity=".8"'))
        parts.append('''<g id="direction-pad" aria-label="Directional pad" transform="translate(400 1217)">
<circle r="102" fill="url(#nav-edge)" stroke="#292b2c" stroke-width="3"/>
<circle r="94" fill="#181a1b" stroke="#0e0f10" stroke-width="3"/>
<circle r="87" fill="url(#nav-ring)" stroke="#797d7d" stroke-width="1.5"/>
<path d="M-70 -47 A87 87 0 0 1 70 -47" fill="none" stroke="#e9eded" stroke-opacity=".72" stroke-width="3"/>
<path d="M-67 54 A87 87 0 0 0 67 54" fill="none" stroke="#9fa3a3" stroke-opacity=".35" stroke-width="2"/>
<g fill="#b5b9b9" stroke="#333536" stroke-width="1"><circle cx="0" cy="-69" r="3.3"/><circle cx="69" cy="0" r="3.3"/><circle cx="0" cy="69" r="3.3"/><circle cx="-69" cy="0" r="3.3"/></g>
<circle r="49" fill="#17191a" stroke="#979c9c" stroke-width="4"/>
<circle id="button-select" aria-label="Select button" r="41" fill="url(#chrome-ball)" stroke="#d8dddd" stroke-width="1.2"/>
<path d="M-29 -19 Q-16 -35 7 -33 M-23 27 Q-4 40 19 29" fill="none" stroke="#fff" stroke-opacity=".66" stroke-width="3" stroke-linecap="round" pointer-events="none"/>
<path id="button-up" aria-label="Up" d="M-57 -71 Q0 -106 57 -71 L34 -42 Q0 -58 -34 -42 Z" fill="transparent" pointer-events="all"/>
<path id="button-right" aria-label="Right" d="M71 -57 Q106 0 71 57 L42 34 Q58 0 42 -34 Z" fill="transparent" pointer-events="all"/>
<path id="button-down" aria-label="Down" d="M-57 71 Q0 106 57 71 L34 42 Q0 58 -34 42 Z" fill="transparent" pointer-events="all"/>
<path id="button-left" aria-label="Left" d="M-71 -57 Q-106 0 -71 57 L-42 34 Q-58 0 -42 -34 Z" fill="transparent" pointer-events="all"/>
</g>
<a id="open-keyboard" href="#open" aria-label="Open keyboard"><title>Open keyboard</title><path d="M50 1003 Q400 921 750 1003 L750 1060 Q400 978 50 1060 Z" fill="transparent" pointer-events="all"/></a>
<a id="close-keyboard" href="#closed" aria-label="Close keyboard"><title>Close keyboard</title><path d="M50 1003 Q400 921 750 1003 L750 1060 Q400 978 50 1060 Z" fill="transparent" pointer-events="all"/></a>
</g>''')
        return "\n".join(parts)


    DEFS = '''<defs>
<linearGradient id="face-horizontal" x1="0" y1="0" x2="1" y2="0">
<stop stop-color="#6f7475"/><stop offset=".018" stop-color="#eceeee"/><stop offset=".045" stop-color="#b3b7b8"/><stop offset=".11" stop-color="#d5d7d7"/><stop offset=".48" stop-color="#c5c8c8"/><stop offset=".89" stop-color="#c2c5c5"/><stop offset=".965" stop-color="#e1e3e3"/><stop offset=".988" stop-color="#969a9b"/><stop offset="1" stop-color="#55595a"/>
</linearGradient>
<linearGradient id="face-vertical" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#fff" stop-opacity=".42"/><stop offset=".09" stop-color="#fff" stop-opacity=".09"/><stop offset=".66" stop-color="#fff" stop-opacity=".02"/><stop offset=".9" stop-color="#000" stop-opacity=".10"/><stop offset="1" stop-color="#000" stop-opacity=".29"/>
</linearGradient>
<linearGradient id="control-face" x1="0" y1="0" x2="1" y2="0">
<stop stop-color="#707475"/><stop offset=".025" stop-color="#bcbebe"/><stop offset=".1" stop-color="#949899"/><stop offset=".48" stop-color="#a1a4a4"/><stop offset=".89" stop-color="#929697"/><stop offset=".97" stop-color="#c2c5c5"/><stop offset="1" stop-color="#696d6e"/>
</linearGradient>
<linearGradient id="control-sheen" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#fff" stop-opacity=".24"/><stop offset=".25" stop-color="#fff" stop-opacity=".03"/><stop offset=".8" stop-color="#000" stop-opacity=".06"/><stop offset="1" stop-color="#000" stop-opacity=".24"/>
</linearGradient>
<linearGradient id="ribbon" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#dfe1e1"/><stop offset=".25" stop-color="#bfc3c3"/><stop offset=".7" stop-color="#eceeee"/><stop offset="1" stop-color="#b4b8b8"/>
</linearGradient>
<linearGradient id="bezel-edge" x1="0" y1="0" x2=".8" y2="1">
<stop stop-color="#a1a5a5"/><stop offset=".2" stop-color="#f0f2f2"/><stop offset=".6" stop-color="#a5a9a9"/><stop offset="1" stop-color="#e2e4e4"/>
</linearGradient>
<linearGradient id="home-face" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#d2d5d4"/><stop offset=".18" stop-color="#aeb2b1"/><stop offset=".85" stop-color="#858a89"/><stop offset="1" stop-color="#c1c5c4"/>
</linearGradient>
<linearGradient id="button-rim" x1="0" y1="0" x2=".2" y2="1">
<stop stop-color="#e5e8e7"/><stop offset=".45" stop-color="#747a79"/><stop offset=".8" stop-color="#d6dada"/><stop offset="1" stop-color="#a1a6a6"/>
</linearGradient>
<linearGradient id="button-face" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#c9cecd"/><stop offset=".18" stop-color="#acb1b0"/><stop offset=".75" stop-color="#858b8a"/><stop offset="1" stop-color="#aab0af"/>
</linearGradient>
<linearGradient id="triangle-edge" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#525859"/><stop offset=".38" stop-color="#858a89"/><stop offset=".82" stop-color="#f3f5f4"/><stop offset="1" stop-color="#a2a7a6"/>
</linearGradient>
<linearGradient id="triangle-face" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#c0c5c4"/><stop offset=".15" stop-color="#a9aeae"/><stop offset=".8" stop-color="#858a8a"/><stop offset="1" stop-color="#9da2a1"/>
</linearGradient>
<linearGradient id="nav-edge" x1="0" y1="0" x2=".15" y2="1">
<stop stop-color="#dbdede"/><stop offset=".15" stop-color="#7b8080"/><stop offset=".53" stop-color="#272a2b"/><stop offset=".83" stop-color="#aaaead"/><stop offset="1" stop-color="#e3e6e5"/>
</linearGradient>
<linearGradient id="nav-ring" x1=".2" y1="0" x2=".75" y2="1">
<stop stop-color="#d4d7d7"/><stop offset=".1" stop-color="#656a69"/><stop offset=".36" stop-color="#303334"/><stop offset=".62" stop-color="#414445"/><stop offset=".85" stop-color="#777b7b"/><stop offset="1" stop-color="#292b2c"/>
</linearGradient>
<radialGradient id="chrome-ball" cx=".35" cy=".28" r=".75">
<stop stop-color="#fff"/><stop offset=".13" stop-color="#e5e8e8"/><stop offset=".3" stop-color="#8f9494"/><stop offset=".46" stop-color="#333637"/><stop offset=".62" stop-color="#17191a"/><stop offset=".76" stop-color="#585d5d"/><stop offset=".9" stop-color="#d7dada"/><stop offset="1" stop-color="#656a6a"/>
</radialGradient>
<linearGradient id="keyboard-bed" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#08090a"/><stop offset=".4" stop-color="#161719"/><stop offset="1" stop-color="#090a0b"/>
</linearGradient>
<linearGradient id="key-light" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#f5f5ec"/><stop offset=".23" stop-color="#d9dcd5"/><stop offset=".78" stop-color="#b9bdb8"/><stop offset="1" stop-color="#8c9290"/>
</linearGradient>
<linearGradient id="key-blue" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#b2b9ec"/><stop offset=".18" stop-color="#6679bf"/><stop offset=".7" stop-color="#344783"/><stop offset="1" stop-color="#202d60"/>
</linearGradient>
<linearGradient id="led-shade" x1="0" y1="0" x2="1" y2="0">
<stop stop-color="#000" stop-opacity=".48"/><stop offset=".4" stop-color="#fff" stop-opacity=".28"/><stop offset=".7" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".4"/>
</linearGradient>
<pattern id="face-brush" width="5" height="4" patternUnits="userSpaceOnUse"><path d="M0 .5 H5" stroke="#fff" stroke-opacity=".015" stroke-width="1"/><path d="M0 2.5 H5" stroke="#000" stroke-opacity=".009" stroke-width=".7"/></pattern>
<filter id="shadow" x="-10%" y="-8%" width="120%" height="120%"><feGaussianBlur stdDeviation="7"/></filter>
</defs>'''


    def face():
        parts = ['''<g id="display-housing">
<path d="M48 77 Q48 68 59 67 L741 67 Q752 68 752 79 L752 990 Q752 1004 742 1006 Q400 922 58 1006 Q48 1004 48 991 Z" fill="#55595a" stroke="#484b4c" stroke-width="2" filter="url(#shadow)" opacity=".4"/>
<path d="M48 78 Q48 68 59 68 L741 68 Q752 69 752 80 L752 990 Q752 1004 742 1006 Q400 922 58 1006 Q48 1004 48 991 Z" fill="url(#face-horizontal)" stroke="#727777" stroke-width="2"/>
<path d="M50 80 Q50 70 60 70 L740 70 Q750 71 750 81 L750 990 Q750 1001 741 1003 Q400 920 59 1003 Q50 1001 50 990 Z" fill="url(#face-vertical)"/>
<path d="M50 80 Q50 70 60 70 L740 70 Q750 71 750 81 L750 990 Q750 1001 741 1003 Q400 920 59 1003 Q50 1001 50 990 Z" fill="url(#face-brush)"/>
<path d="M61 75 H739 M55 89 V972 M745 89 V972" fill="none" stroke="#fff" stroke-opacity=".42" stroke-width="2"/>
<rect x="102" y="126" width="596" height="763" rx="4" fill="url(#bezel-edge)" stroke="#969b9b" stroke-width="2"/>
<rect x="110" y="134" width="580" height="748" rx="2" fill="#333637" stroke="#f2f4f3" stroke-opacity=".65" stroke-width="1.5"/>
<rect x="118" y="143" width="564" height="735" rx="1.5" fill="#101214"/>
<path d="M123 149 H677 M123 149 V873" fill="none" stroke="#707575" stroke-opacity=".55" stroke-width="2"/>
<rect id="screen" x="137.5" y="168" width="525" height="700" fill="#c3c6c9"/>''']
        parts.append(text_path("SHARP", 400, 922, 22, face="bold", width=150, fill="#555a5a"))
        parts.append('''<g stroke="#666b6b" stroke-width="2" fill="none" stroke-linejoin="round" opacity=".8">
<rect x="163" y="926" width="22" height="14" rx="1"/><path d="M163 927 L174 935 185 927"/>
<path d="M211 930 H218 M215 927 L219 930 215 933 M222 925 H244 V936 H222 Z M244 928 H247 V933 H244"/>
</g>
<path d="M52 1000 Q400 916 748 1000" fill="none" stroke="#292b2c" stroke-width="7" stroke-opacity=".75"/>
<path d="M55 997 Q400 914 745 997" fill="none" stroke="#d5d8d7" stroke-width="1.5" stroke-opacity=".5"/>
<path id="led-mail" aria-label="Mail indicator" d="M174 947 Q180 947 182 953 L183 969 Q183 973 179 974 L174 974 Q170 973 170 969 L170 953 Q170 948 174 947 Z" fill="#252626" stroke="#747878" stroke-width="1.5"/>
<path d="M174 947 Q180 947 182 953 L183 969 Q183 973 179 974 L174 974 Q170 973 170 969 L170 953 Q170 948 174 947 Z" fill="url(#led-shade)" pointer-events="none"/>
<path id="led-charge" aria-label="Charge indicator" d="M230 945 Q236 945 238 951 L239 966 Q239 971 235 972 L230 972 Q226 971 226 967 L226 951 Q226 946 230 945 Z" fill="#ffb823" stroke="#747878" stroke-width="1.5"/>
<path d="M230 945 Q236 945 238 951 L239 966 Q239 971 235 972 L230 972 Q226 971 226 967 L226 951 Q226 946 230 945 Z" fill="url(#led-shade)" pointer-events="none"/>
</g>''')
        return "\n".join(parts)


    return dict(defs=DEFS, keyboard=keyboard(), slider=slider(), face=face(), band=embossed_band(), icons=ICONS)


def build_sl5500(fonts):
    parts = sliding_parts(fonts)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" id="collie" viewBox="0 40 800 1380" preserveAspectRatio="xMidYMin meet" role="group" aria-labelledby="title description">
<!--
  Sharp Zaurus SL-5500 (Collie), front view. Screen: x=137.5 y=168,
  width=525 height=700 (240 x 320 at 2.1875 units per pixel).
  SPDX-FileCopyrightText: 2026 Koen Kooi
  SPDX-License-Identifier: CC-BY-SA-4.0
  Original vector drawing based on supplied photographs and measurements of
  "Sharp Zaurus SL-5500G.jpg" by Wusel007 (CC BY-SA 3.0). No photo is embedded.
  Printed lettering uses Open Sans outlines (SIL OFL 1.1).
  SHARP and Zaurus are trademarks used only to identify the device.
-->
<title id="title">Sharp Zaurus SL-5500</title>
<desc id="description">Front view of the silver Zaurus with a sliding QWERTY keyboard. The screen is a 240 by 320 frame.</desc>
<view id="closed" viewBox="0 40 800 1380"/>
<view id="open" viewBox="0 40 800 1670"/>
<style>
  #close-keyboard {{ display: none }}
  #open:target ~ #art #slider, #collie[data-keyboard="open"] #slider {{ transform: translate(0, 290px) }}
  #open:target ~ #art #open-keyboard, #collie[data-keyboard="open"] #open-keyboard {{ display: none }}
  #open:target ~ #art #close-keyboard, #collie[data-keyboard="open"] #close-keyboard {{ display: inline }}
</style>
{parts['defs']}
<g id="art">
{parts['keyboard']}
{parts['slider']}
{parts['face']}
</g>
</svg>
'''


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"expected exactly one occurrence of {old[:80]!r}")
    return text.replace(old, new)


def build_sl5600(fonts):
    parts = sliding_parts(fonts)
    def make_defs():
        definitions = parts['defs']
        definitions = replace_once(definitions,
            '<stop stop-color="#707475"/><stop offset=".025" stop-color="#bcbebe"/><stop offset=".1" stop-color="#949899"/><stop offset=".48" stop-color="#a1a4a4"/><stop offset=".89" stop-color="#929697"/><stop offset=".97" stop-color="#c2c5c5"/><stop offset="1" stop-color="#696d6e"/>',
            '<stop stop-color="#899094"/><stop offset=".025" stop-color="#f2f4f4"/><stop offset=".1" stop-color="#c9cdcf"/><stop offset=".48" stop-color="#dcdee0"/><stop offset=".89" stop-color="#c1c6c8"/><stop offset=".97" stop-color="#e8ecec"/><stop offset="1" stop-color="#808689"/>')
        definitions = replace_once(definitions,
            '<stop stop-color="#dfe1e1"/><stop offset=".25" stop-color="#bfc3c3"/><stop offset=".7" stop-color="#eceeee"/><stop offset="1" stop-color="#b4b8b8"/>',
            '<stop stop-color="#555a60"/><stop offset=".17" stop-color="#32363c"/><stop offset=".7" stop-color="#202329"/><stop offset="1" stop-color="#111316"/>')
        definitions = replace_once(definitions,
            '<stop stop-color="#d4d7d7"/><stop offset=".1" stop-color="#656a69"/><stop offset=".36" stop-color="#303334"/><stop offset=".62" stop-color="#414445"/><stop offset=".85" stop-color="#777b7b"/><stop offset="1" stop-color="#292b2c"/>',
            '<stop stop-color="#f4f7f8"/><stop offset=".1" stop-color="#929b9e"/><stop offset=".3" stop-color="#e2e7e8"/><stop offset=".49" stop-color="#a8b1b3"/><stop offset=".7" stop-color="#6b7478"/><stop offset=".86" stop-color="#d4dadb"/><stop offset="1" stop-color="#6b7478"/>')
        return definitions


    def make_slider():
        slider = parts['slider']
        old_band = parts['band']
        new_band = old_band.replace('opacity=".7"', 'opacity=".25"').replace(
            'fill="#6d7372"', 'fill="#afb4b6"')
        slider = replace_once(slider, old_band, new_band)
        slider = replace_once(slider,
            '<path d="M53 1008 Q400 927 747 1008 M52 1058 Q400 976 748 1058" fill="none" stroke="#fff" stroke-opacity=".65" stroke-width="2"/>',
            '<path d="M53 1008 Q400 927 747 1008 M52 1058 Q400 976 748 1058" fill="none" stroke="#fff" stroke-opacity=".28" stroke-width="2"/>')
        slider = replace_once(slider, parts['icons']["calendar"],
            '<rect x="-14" y="-12" width="28" height="24" rx="1"/><path d="M-14 -5 H14 M-5 -12 V12 M5 -12 V12 M-14 3 H14"/>')
        before = '<g id="button-cancel" aria-label="Cancel / power button"'
        microphone = '''<g id="mark-microphone" aria-label="Microphone symbol" transform="translate(185 1163) rotate(25)" fill="none" stroke="#555b5a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" opacity=".85" pointer-events="none">
<rect x="-4" y="-10" width="8" height="14" rx="4"/>
<path d="M-7 -3 V0 A7 7 0 0 0 7 0 V-3 M0 7 V12 M-4 12 H4"/>
</g>
'''
        slider = replace_once(slider, before, microphone + before)
        return slider


    def make_keyboard():
        keyboard = parts['keyboard']
        keyboard = replace_once(keyboard,
            "L741 1324 Q400 1232 59 1324 Z",
            "L741 1360 Q400 1340 59 1360 Z")
        keyboard = replace_once(keyboard, "M64 966 V1314 M736 966 V1314", "M64 966 V1350 M736 966 V1350")
        keyboard = replace_once(keyboard, "M70 1307 Q400 1221 730 1307", "M70 1353 Q400 1330 730 1353")
        root = ET.fromstring(keyboard)
        row1 = {f"key-{char}" for char in "qwertyuiop"}
        row2 = {f"key-{char}" for char in "asdfghjkl"} | {"key-backspace"}
        row3 = {f"key-{char}" for char in "zxcvbnm"} | {"key-shift-left", "key-shift-right", "key-comma-semicolon"}
        bottom = dict(zip(("key-fn", "key-tab", "key-slash", "key-space", "key-quote", "key-period", "key-enter"),
                          (41, 44, 48, 52, 48, 44, 41)))
        shift = None
        for child in root:
            key_id = child.get("id")
            if key_id:
                if key_id in row1:
                    shift = 25
                elif key_id in row2:
                    shift = 30.5
                elif key_id in row3:
                    shift = 36
                else:
                    shift = bottom[key_id]
                child.set("transform", f'translate(0 {fmt3(shift)}) {child.attrib["transform"]}')
            elif shift is not None:
                child.set("transform", f'translate(0 {fmt3(shift)})')
        return ET.tostring(root, encoding="unicode")


    def build():
        return f'''<svg xmlns="http://www.w3.org/2000/svg" id="poodle" viewBox="0 40 800 1380" preserveAspectRatio="xMidYMin meet" role="group" aria-labelledby="title description">
<!--
  Original vector drawing of the Sharp Zaurus SL-5600 (Poodle).
  SPDX-FileCopyrightText: 2026 Koen Kooi
  SPDX-License-Identifier: CC-BY-SA-4.0
  Geometry informed by device photographs; no photograph is embedded.
  Printed lettering uses Open Sans outlines (SIL OFL 1.1).
  Sharp and Zaurus are trademarks used only to identify the device.
-->
<title id="title">Sharp Zaurus SL-5600</title>
<desc id="description">Front view of the silver SL-5600 with a sliding QWERTY keyboard and a 240 by 320 screen.</desc>
<view id="closed" viewBox="0 40 800 1380"/>
<view id="open" viewBox="0 40 800 1750"/>
<style>
  #close-keyboard {{ display: none }}
  #open:target ~ #art #slider, #poodle[data-keyboard="open"] #slider {{ transform: translate(0, 370px) }}
  #open:target ~ #art #open-keyboard, #poodle[data-keyboard="open"] #open-keyboard {{ display: none }}
  #open:target ~ #art #close-keyboard, #poodle[data-keyboard="open"] #close-keyboard {{ display: inline }}
</style>
{make_defs()}
<g id="art">
{make_keyboard()}
{make_slider()}
{parts['face']}
</g>
</svg>
'''

    return build()


def build_c700(fonts, view):
    """Draw either C700 view; the laptop deck uses a projective plane."""
    f = fmt3
    text = fonts.text_path

    DEFS = """<defs>
<linearGradient id="shell" x1="0" y1="0" x2="1" y2="0">
<stop stop-color="#777d82"/><stop offset=".025" stop-color="#f8fafc"/><stop offset=".09" stop-color="#d5d9de"/><stop offset=".48" stop-color="#e7e9ed"/><stop offset=".9" stop-color="#c5cbd0"/><stop offset=".975" stop-color="#fbfcfd"/><stop offset="1" stop-color="#8f969b"/>
</linearGradient>
<linearGradient id="shell-light" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#fff" stop-opacity=".48"/><stop offset=".35" stop-color="#fff" stop-opacity=".08"/><stop offset=".8" stop-color="#000" stop-opacity=".03"/><stop offset="1" stop-color="#000" stop-opacity=".22"/>
</linearGradient>
<linearGradient id="deck" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#f1f2f5"/><stop offset=".16" stop-color="#c7cbd3"/><stop offset=".62" stop-color="#d9dce1"/><stop offset="1" stop-color="#a1a8b0"/>
</linearGradient>
<linearGradient id="hinge" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#777e86"/><stop offset=".08" stop-color="#f8fbff"/><stop offset=".27" stop-color="#d1d6dd"/><stop offset=".62" stop-color="#c2c8ce"/><stop offset=".9" stop-color="#eff2f5"/><stop offset="1" stop-color="#7c848c"/>
</linearGradient>
<linearGradient id="hinge-vertical" x1="0" y1="0" x2="1" y2="0">
<stop stop-color="#858c92"/><stop offset=".13" stop-color="#f7f9fa"/><stop offset=".42" stop-color="#c4cbd0"/><stop offset=".75" stop-color="#eef1f3"/><stop offset="1" stop-color="#7a8084"/>
</linearGradient>
<linearGradient id="dark-key" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#37373d"/><stop offset=".18" stop-color="#24242a"/><stop offset=".85" stop-color="#17181c"/><stop offset="1" stop-color="#08090c"/>
</linearGradient>
<linearGradient id="light-key" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#fafbfc"/><stop offset=".22" stop-color="#dde0e5"/><stop offset=".8" stop-color="#b7bdc5"/><stop offset="1" stop-color="#929aa4"/>
</linearGradient>
<linearGradient id="button" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#f8fafb"/><stop offset=".25" stop-color="#d7dbe0"/><stop offset=".8" stop-color="#acb3bc"/><stop offset="1" stop-color="#e3e7e9"/>
</linearGradient>
<linearGradient id="bezel" x1="0" y1="0" x2="1" y2="1">
<stop stop-color="#24272a"/><stop offset=".22" stop-color="#0e1012"/><stop offset=".75" stop-color="#151719"/><stop offset="1" stop-color="#383c3e"/>
</linearGradient>
<linearGradient id="led-shade" x1="0" y1="0" x2="1" y2="0">
<stop stop-color="#000" stop-opacity=".48"/><stop offset=".4" stop-color="#fff" stop-opacity=".28"/><stop offset=".7" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".4"/>
</linearGradient>
<filter id="shadow" x="-10%" y="-10%" width="120%" height="125%"><feGaussianBlur stdDeviation="7"/></filter>
</defs>"""


    def root_start(name, viewbox, title, description):
        return f'''<svg xmlns="{SVG_NS}" id="{name}" viewBox="{viewbox}" role="group" aria-labelledby="title description">
<!--
  Original vector drawing of the Sharp Zaurus SL-C700.
  SPDX-FileCopyrightText: 2026 Koen Kooi
  SPDX-License-Identifier: CC-BY-SA-4.0
  Geometry informed by device photographs; no photograph is embedded.
  Lettering uses Open Sans and Noto Sans CJK JP outlines (SIL OFL 1.1).
  Sharp and Zaurus are trademarks used only to identify the device.
-->
<title id="title">{escape(title)}</title>
<desc id="description">{escape(description)}</desc>
{DEFS}'''


    def project_matrix():
        # A 1000 x 250 keyboard plane maps onto the four measured deck corners.
        top_left, top_right = (128, 945), (1171, 945)
        bottom_left, bottom_right = (103, 1195), (1194, 1195)
        top_width = top_right[0] - top_left[0]
        bottom_width = bottom_right[0] - bottom_left[0]
        ratio = top_width / bottom_width
        return ((top_width / 1000, (bottom_left[0] * ratio - top_left[0]) / 250, top_left[0]),
                (0.0, (bottom_left[1] * ratio - top_left[1]) / 250, top_left[1]),
                (0.0, (ratio - 1) / 250, 1.0))


    def project(matrix, x, y):
        value = [row[0] * x + row[1] * y + row[2] for row in matrix]
        return value[0] / value[2], value[1] / value[2]


    def plane_at(matrix, x, y):
        px, py = project(inverse3(matrix), x, y)
        origin = project(matrix, px, py)
        dx = project(matrix, px + 1, py)
        dy = project(matrix, px, py + 1)
        return px, py, 1 / (dx[0] - origin[0]), 1 / (dy[1] - origin[1])


    def plane_point(matrix, plane, x, y):
        px, py, sx, sy = plane
        return project(matrix, px + x * sx, py + y * sy)


    def plane_transform(matrix, plane, x=0, y=0):
        px, py = plane_point(matrix, plane, x, y)
        vx = plane_point(matrix, plane, x + 1, y)
        vy = plane_point(matrix, plane, x, y + 1)
        return f"matrix({f(vx[0]-px)} {f(vx[1]-py)} {f(vy[0]-px)} {f(vy[1]-py)} {f(px)} {f(py)})"


    def plane_polygon(matrix, plane, points):
        return " ".join(f"{f(x)},{f(y)}" for x, y in (plane_point(matrix, plane, *point) for point in points))


    def plane_roundrect(matrix, plane, x, y, width, height, radius):
        points = []
        for cx, cy, start in ((x + width - radius, y + radius, -90),
                              (x + width - radius, y + height - radius, 0),
                              (x + radius, y + height - radius, 90),
                              (x + radius, y + radius, 180)):
            for angle in (start + 15 * i for i in range(7)):
                radians = math.radians(angle)
                points.append((cx + radius * math.cos(radians), cy + radius * math.sin(radians)))
        return plane_polygon(matrix, plane, points)


    def plane_ellipse(matrix, plane, x, y, rx, ry):
        return plane_polygon(matrix, plane, [(x + rx * math.cos(angle), y + ry * math.sin(angle))
                                             for angle in (i * (2 * math.pi / 48) for i in range(48))])


    def key(matrix, name, label, x, y, width, height, *, light=False, cap=20, secondary="", corner="", lower=""):
        outline = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
        if name == "enter":
            outline = [(x, y), (x + width, y), (x + width, y + height),
                       (x + 24, y + height), (x + 24, y + 47), (x, y + 47)]
        corners = [project(matrix, px, py) for px, py in outline]
        points = " ".join(f"{f(px)},{f(py)}" for px, py in corners)
        cx, cy = x + width / 2, y + (24 if name == "enter" else height / 2)
        px, py = project(matrix, cx, cy)
        vx = project(matrix, cx + 1, cy)
        vy = project(matrix, cx, cy + 1)
        affine = f"matrix({f(vx[0]-px)} {f(vx[1]-py)} {f(vy[0]-px)} {f(vy[1]-py)} {f(px)} {f(py)})"
        fill = "url(#light-key)" if light else "url(#dark-key)"
        legend = "#282b2e" if light else "#e4e6eb"
        parts = [f'<g id="key-{name}" aria-label="{escape(label or name)}">',
                 f'<polygon points="{points}" fill="{fill}" stroke="#111318" stroke-width="1.5" stroke-linejoin="round"/>',
                 f'<g transform="{affine}">']
        if name == "kana":
            parts.append(text("カナ", 0, -2, 12, face="jp", fill=legend))
            parts.append(text("ひら", 0, 15, 12, face="jp", fill=legend))
        elif name == "space":
            parts.append(text("前候補", 0, -7, 11, face="jp", fill=legend))
            parts.append(text(label, 0, 13, cap, face="jp", fill=legend))
        elif label:
            face = "jp" if any(ord(char) > 127 for char in label) else "regular"
            parts.append(text(label, 8 if corner else 0, cap * .37 + (3 if corner else 0), cap, face=face, fill=legend))
        if corner:
            parts.append(text(corner, -19, -4, 10, fill=legend))
        if name == "backspace":
            parts.append('<path d="M-21 -5 L-29 0 -21 5 V2 H-12 V-2 H-21 Z" fill="#282b2e"/>')
        if name == "enter":
            parts.append('<path d="M27 21 V31 H9 M15 26 L9 31 15 36" fill="none" stroke="#e4e6eb" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>')
        if lower:
            parts.append(text(lower, 0, 20, 9, face="jp", fill=legend))
        parts.append("</g>")
        if secondary:
            sx, sy = project(matrix, cx, y - 3)
            parts.append(f'<g transform="{plane_transform(matrix, plane_at(matrix, sx, sy))}">')
            parts.append(text(secondary, 0, 0, 9.5, face="jp" if any(ord(char) > 127 for char in secondary) else "bold", fill="#9d8bc5"))
            parts.append("</g>")
        parts.append("</g>")
        return "\n".join(parts)


    def shortcut_strip(view):
        glyphs = {
            "home": '<path fill-rule="evenodd" d="M-11 -1 L0 -11 11 -1 H8 V10 H-8 V-1 Z M-2 10 H2 V3 H-2 Z"/>',
            "mail": '<path fill-rule="evenodd" d="M-10 -7 H10 V7 H-10 Z M-8 -5 L0 1 8 -5 V-2.5 L0 3.5 -8 -2.5 Z"/>',
            "address": '<circle cy="-6.5" r="4"/><path d="M-7 10 V3.5 Q-7 -1 0 -1 Q7 -1 7 3.5 V10 Z"/>',
            "calendar": '<path fill-rule="evenodd" d="M-9 -10 H9 V10 H-9 Z ' +
                        " ".join(f"M{x} {y} h2.5 v2.5 h-2.5 Z"
                                 for y in (-4.5, -.25, 4) for x in (-5.5, -1.25, 3)) + '"/>',
            "clock": '<path d="M0 -10 V10 M-10 0 H10 M-7 -7 L7 7 M7 -7 L-7 7" fill="none" stroke="#8b9296" stroke-width="3" stroke-linecap="round"/>',
        }
        positions = {
            "laptop": (("home", 995, 161), ("mail", 995, 249), ("address", 995, 341),
                       ("calendar", 995, 434), ("clock", 995, 520)),
            "pda": (("clock", 329, 879), ("calendar", 397, 879), ("address", 464, 879),
                    ("mail", 535, 879), ("home", 600, 879)),
        }
        # Printed shortcuts turn with the lid, not with the screen contents.
        angle = -60 if view == "laptop" else 30
        return "\n".join(
            f'''<g id="touch-{name}" aria-label="{name.title()} shortcut" transform="translate({x} {y})">
<rect x="-21" y="-20" width="42" height="40" fill="transparent" stroke="none" pointer-events="all"/>
<g data-shortcut="{name}" transform="rotate({angle})" fill="#8b9296">{glyphs[name]}</g>
</g>''' for name, x, y in positions[view])


    def app_button(matrix, name, label, x, icon):
        plane = plane_at(matrix, x, 1252)
        face = plane_roundrect(matrix, plane, -40, -35, 80, 70, 6)
        parts = [f'<g id="button-{name}" aria-label="{escape(label)}">',
                 f'<polygon points="{face}" fill="url(#button)" stroke="#858c94" stroke-width="2"/>',
                 f'<g transform="{plane_transform(matrix, plane)}">',
                 '<path d="M-33 -28 H33" fill="none" stroke="#fff" stroke-opacity=".8" stroke-width="2"/>',
                 text(label, 0, -6, 12, fill="#323638"),
                 f'<g transform="translate(0 10)" fill="none" stroke="#31363a" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">{icon}</g>',
                 "</g></g>"]
        return "\n".join(parts)


    def laptop():
        parts = [root_start("c700-laptop", "0 0 1300 1450", "Sharp Zaurus SL-C700, laptop view",
                            "Open SL-C700 with a perspective keyboard and a landscape 640 by 480 screen.")]
        parts += ['''<path d="M92 60 Q92 31 121 31 H1180 Q1210 31 1210 60 L1200 682 Q1200 714 1172 717 H128 Q100 714 100 682 Z" fill="#373a3d" opacity=".3" filter="url(#shadow)"/>
<path d="M92 60 Q92 31 121 31 H1180 Q1210 31 1210 60 L1200 682 Q1200 714 1172 717 H128 Q100 714 100 682 Z" fill="url(#shell)" stroke="#8b9098" stroke-width="3"/>
<path d="M98 64 Q98 37 124 37 H1176 Q1204 37 1204 65 L1194 678 Q1194 706 1171 709 H129 Q106 706 106 678 Z" fill="url(#shell-light)"/>
<path d="M126 45 H1173" stroke="#fff" stroke-width="3" opacity=".65"/>
<rect x="202" y="72" width="896" height="581" rx="14" fill="#0c0e0f" stroke="#6b7176" stroke-width="3"/>
<rect x="213" y="81" width="875" height="563" rx="8" fill="url(#bezel)" stroke="#292e32" stroke-width="2"/>
<rect id="screen" x="255" y="92" width="700" height="525" fill="#c3c6c9"/>
<path d="M250 88 H959 M249 88 V622" fill="none" stroke="#596167" stroke-opacity=".35" stroke-width="2"/>
''']
        parts.append(shortcut_strip("laptop"))
        parts.append(text("CG Silicon", 1066, 573, 14, fill="#939a9c", extra='transform="rotate(-90 1066 573)"'))
        parts += ['''<path d="M112 721 H1186 Q1193 721 1193 730 V807 Q1193 818 1181 820 H119 Q108 818 108 807 V730 Q108 723 112 721 Z" fill="url(#hinge)" stroke="#7d848b" stroke-width="3"/>
<path d="M120 734 H1181 M120 808 H1180" stroke="#fff" stroke-opacity=".5" stroke-width="2"/>
<path d="M461 718 H840 V810 H461 Z" fill="url(#hinge)" stroke="#8d9399" stroke-width="2"/>
<path d="M464 722 H837 M462 804 H839" stroke="#f8fafb" stroke-opacity=".65" stroke-width="2"/>''']
        parts.append(text("SHARP", 650, 761, 20, face="bold", width=166, fill="#828991"))
        parts.append(text("PERSONAL MOBILE TOOL", 1090, 774, 8, fill="#858c92"))
        parts += ['''<g fill="none" stroke="#747c83" stroke-width="2"><path d="M150 741 h16 v8 h-16 z M166 743 h3 v4 h-3"/><path d="M150 781 h16 v10 h-16 z M150 782 l8 5 8 -5"/></g>
<rect id="led-charge" x="130" y="740" width="8" height="13" rx="3" fill="#252626"/>
<rect x="130" y="740" width="8" height="13" rx="3" fill="url(#led-shade)" pointer-events="none"/>
<rect id="led-mail" x="130" y="779" width="8" height="13" rx="3" fill="#252626"/>
<rect x="130" y="779" width="8" height="13" rx="3" fill="url(#led-shade)" pointer-events="none"/>
<circle cx="751" cy="816" r="7" fill="#303338"/><circle cx="749" cy="814" r="2" fill="#9ca4a7"/>
<path d="M104 839 Q100 824 117 823 H1183 Q1200 824 1196 839 L1240 1286 L1250 1349 Q1251 1371 1225 1375 H75 Q49 1371 50 1349 L60 1286 Z" fill="#30343a" opacity=".28" filter="url(#shadow)"/>
<path d="M104 839 Q100 824 117 823 H1183 Q1200 824 1196 839 L1240 1286 L1250 1349 Q1251 1371 1225 1375 H75 Q49 1371 50 1349 L60 1286 Z" fill="url(#shell)" stroke="#747c84" stroke-width="3"/>
<path d="M116 849 Q116 838 129 838 H1171 Q1184 838 1184 849 L1229 1283 L1238 1338 Q1239 1356 1219 1359 H81 Q61 1356 62 1338 L71 1283 Z" fill="url(#deck)" stroke="#a5aab1" stroke-width="3"/>
<path d="M134 849 H1166" stroke="#fff" stroke-width="3" stroke-opacity=".8"/>
''']
        matrix = project_matrix()

        def plane_x_at(a, b, y):
            # Screen lines stay lines in the keyboard plane, so the shell edge interpolates exactly.
            (ax, ay), (bx, by) = project(inverse3(matrix), *a), project(inverse3(matrix), *b)
            return ax + (bx - ax) * (y - ay) / (by - ay)

        def corner(cx, cy, start, radius=8):
            return [(cx + radius * math.cos(math.radians(start + 15 * i)),
                     cy + radius * math.sin(math.radians(start + 15 * i))) for i in range(7)]

        # Measured on a close-up of the C700 deck: the inset steps up beside the Fn key
        # and beneath Enter, leaving room for Fn and the up arrow on the silver deck.
        top_left, top_right = project(inverse3(matrix), 121, 940), project(inverse3(matrix), 1178, 940)
        step, bottom, fn_wall, arrow_wall = 208, 252.9, 147, 784
        outline = [top_left, top_right, (plane_x_at((1178, 940), (1201, 1198), step), step)]
        outline += corner(arrow_wall + 8, step + 8, 180)[::-1]
        outline += corner(arrow_wall - 8, bottom - 8, 0)
        outline += corner(fn_wall + 8, bottom - 8, 90)
        outline += corner(fn_wall - 8, step + 8, -90)[::-1]
        outline.append((plane_x_at((121, 940), (99, 1198), step), step))
        inset = " ".join(f"{f(x)},{f(y)}" for x, y in (project(matrix, *point) for point in outline))
        parts.append(f'<polygon id="keyboard-inset" points="{inset}" fill="#101114" stroke="#5d6267" stroke-width="3" stroke-linejoin="round"/>')
        parts.append('<path d="M125 947 H1175" stroke="#44474d" stroke-opacity=".6" stroke-width="2"/>')
        for i, (digit, shifted) in enumerate(zip("1234567890", ['!', '"', '#', '$', '%', '&', "'", '(', ')', '~'])):
            parts.append(key(matrix, f"digit-{digit}", digit, 20 + i * 87, -39, 62, 33, light=True, cap=17, corner=shifted,
                             secondary={5: "あ", 6: "ア", 7: "ｱ", 8: "A", 9: "A"}.get(i, "")))
        parts.append(key(matrix, "backspace", "BS", 905, -39, 75, 33, light=True, cap=14, secondary="Del"))
        for i, char in enumerate("QWERTYUIOP"):
            parts.append(key(matrix, char.lower(), char, 17 + 97 * i, 9, 75, 48, cap=21,
                             secondary={"W": "^", "E": "=", "R": "+", "T": "[", "Y": "]", "U": "「", "I": "」"}.get(char, "")))
        parts.append(key(matrix, "tab", "Tab", 17, 72, 65, 47, cap=14, secondary="Caps"))
        for i, char in enumerate("ASDFGHJKL"):
            parts.append(key(matrix, char.lower(), char, 101 + i * 97, 72, 75, 47, cap=21,
                             secondary={"D": ".", "F": "`", "G": ";", "H": ":", "J": "*", "K": "¥", "L": "|"}.get(char, "")))
        parts.append(key(matrix, "shift-left", "⇧", 17, 132, 65, 47, cap=19))
        for i, char in enumerate("ZXCVBNM"):
            second = {"X": "Cut", "C": "Copy", "V": "Paste", "B": "_"}.get(char, "")
            parts.append(key(matrix, char.lower(), char, 101 + i * 97, 132, 75, 47, cap=21, secondary=second))
        parts.append(key(matrix, "shift-right", "⇧", 790, 132, 70, 47, cap=19))
        parts.append(key(matrix, "enter", "Enter", 880, 132, 96, 68, cap=14))
        # Bottom-row positions are measured from a close-up photo, scaled by the letter-key pitch.
        parts.append(key(matrix, "kana", "カナ/ひら", 165, 191, 53, 48, cap=9, secondary="記号"))
        parts.append(key(matrix, "zenkaku", "全/半", 240, 191, 53, 48, cap=10, secondary="漢字"))
        parts.append(key(matrix, "minus", "-", 313, 191, 55, 48, cap=20, secondary="@"))
        parts.append(key(matrix, "space", "Space/変換", 395, 191, 194, 48, cap=15, secondary="音訓"))
        parts.append(key(matrix, "slash", "/", 615, 191, 55, 48, cap=19, secondary="<", lower="、"))
        parts.append(key(matrix, "question", "?", 691, 191, 55, 48, cap=19, secondary=">", lower="。・"))
        fn_plane = plane_at(matrix, 174, 1177)
        parts.append('<g id="key-fn" aria-label="Fn">')
        parts.append(f'<polygon points="{plane_roundrect(matrix, fn_plane, -47, -22, 94, 44, 9)}" fill="#8f79c7"/>')
        parts.append(f'<polygon points="{plane_roundrect(matrix, fn_plane, -41, -18, 82, 35, 5)}" fill="url(#light-key)" stroke="#a5aab0" stroke-width="1.5"/>')
        parts.append(f'<g transform="{plane_transform(matrix, fn_plane)}">')
        parts.append(text("Fn", 0, 6, 17, face="bold", fill="#44424e"))
        parts.append("</g></g>")
        icons = {
            "calendar": '<rect x="-11" y="-9" width="22" height="20"/><path d="M-11 -3 H11 M-5 -12 V-6 M5 -12 V-6 M-5 2 V7 M1 2 V7"/>',
            "address": '<circle cx="0" cy="-6" r="5"/><path d="M-12 11 Q-10 2 0 2 Q10 2 12 11"/>',
            "mail": '<rect x="-13" y="-8" width="26" height="18"/><path d="M-13 -7 L0 2 13 -7"/>',
            "home": '<path d="M-13 0 L0 -11 13 0 M-10 -2 V10 H10 V-2 M-3 10 V3 H3 V10"/>',
            "menu": '<rect x="-11" y="-10" width="22" height="21"/><path d="M-7 -5 H7 M-7 0 H7 M-7 5 H4"/>',
        }
        for name, label, x in [("calendar", "Calendar", 170), ("address", "Address", 270),
                               ("mail", "Mail", 370), ("home", "Home", 470),
                               ("menu", "Menu", 800)]:
            parts.append(app_button(matrix, name, label, x, icons[name]))
        for label, x in [("Sync", 170), ("Check", 370)]:
            parts.append(f'<g transform="{plane_transform(matrix, plane_at(matrix, x, 1309))}">')
            parts.append(text(label, 0, 0, 10, fill="#44494d"))
            parts.append("</g>")
        rocker_plane = plane_at(matrix, 633.5, 1251.5)
        rocker = plane_roundrect(matrix, rocker_plane, -98.5, -36.5, 197, 73, 14)
        parts.append(f'<polygon points="{rocker}" fill="url(#dark-key)" stroke="#777b84" stroke-width="2"/>')
        divider = plane_polygon(matrix, rocker_plane, [(.5, -30.5), (.5, 30.5)])
        parts.append(f'<polyline points="{divider}" fill="none" stroke="#44484f" stroke-width="2"/>')
        for name, label, x, left, right in [("cancel", "Cancel", -49.5, -98.5, -.5),
                                             ("ok", "OK", 50.5, 2.5, 98.5)]:
            face = plane_polygon(matrix, rocker_plane, [(left, -36.5), (right, -36.5),
                                                        (right, 36.5), (left, 36.5)])
            parts.append(f'<g id="button-{name}" aria-label="{label}">')
            parts.append(f'<polygon points="{face}" fill="transparent" pointer-events="all"/>')
            parts.append(f'<g transform="{plane_transform(matrix, rocker_plane, x, 0)}">')
            parts.append(text(label, 0, -10.5, 14 if name == "cancel" else 16, fill="#e9ebed"))
            if name == "cancel":
                parts.append(text("×", 0, 20.5, 20, face="jp", fill="#e9ebed"))
            else:
                parts.append('<circle cy="13.5" r="9" fill="#e9ebed"/>')
            parts.append("</g></g>")
        # Arrow centres share keyboard-plane columns, so Up sits squarely above Down.
        for name, x, y, angle in [("left", 757, 313, -90), ("down", 851, 313, 180),
                                  ("right", 945, 313, 90), ("up", 849, 222, 0)]:
            def oval(dx, dy, rx, ry):
                # A superellipse matches the flattened sides of the moulded buttons.
                return " ".join(
                    f"{f(px)},{f(py)}" for px, py in (project(
                        matrix,
                        x + dx + rx * math.copysign(abs(math.cos(a)) ** .9, math.cos(a)),
                        y + dy + ry * math.copysign(abs(math.sin(a)) ** .9, math.sin(a)))
                        for a in (i * 2 * math.pi / 64 for i in range(64))))
            px, py = project(matrix, x, y)
            vx, vy = project(matrix, x + 1, y), project(matrix, x, y + 1)
            affine = f"matrix({f(vx[0]-px)} {f(vx[1]-py)} {f(vy[0]-px)} {f(vy[1]-py)} {f(px)} {f(py)})"
            parts.append(f'<g id="button-{name}" aria-label="{name}">')
            parts.append(f'<polygon points="{oval(0, 3, 39, 32)}" fill="#8b9199" opacity=".5"/>')
            parts.append(f'<polygon points="{oval(0, 0, 37, 30)}" fill="url(#button)" stroke="#a0a7ad" stroke-width="2"/>')
            parts.append(f'<polygon points="{oval(0, -3, 27, 19)}" fill="#fff" opacity=".18" pointer-events="none"/>')
            parts.append(f'<g transform="{affine}">')
            parts.append(f'<path d="M0 -14 L-8 -2 H-3 V14 H3 V-2 H8 Z" transform="rotate({angle})" fill="#30343a"/>')
            parts.append("</g></g>")
        parts.append("</svg>")
        return "\n".join(parts)


    def pda():
        parts = [root_start("c700-pda", "0 0 800 1170", "Sharp Zaurus SL-C700, folded view",
                            "Folded SL-C700 with a portrait 480 by 640 screen.")]
        parts += ['''<rect x="94" y="51" width="660" height="1050" rx="26" fill="#30343a" opacity=".28" filter="url(#shadow)"/>
<rect x="94" y="51" width="660" height="1050" rx="26" fill="url(#shell)" stroke="#7e858a" stroke-width="3"/>
<rect x="100" y="57" width="648" height="1038" rx="22" fill="url(#shell-light)"/>
<path d="M122 65 H724 M744 78 V1077" fill="none" stroke="#fff" stroke-opacity=".6" stroke-width="3"/>
<rect x="38" y="64" width="68" height="1027" rx="16" fill="url(#hinge-vertical)" stroke="#838b91" stroke-width="3"/>
<path d="M42 67 H102 M42 448 H102 M42 1036 H102 M42 1087 H102" stroke="#8a9297" stroke-width="4"/>
<path d="M52 78 V1071" stroke="#fff" stroke-opacity=".65" stroke-width="3"/>
<rect id="led-charge" x="51" y="1062" width="13" height="8" rx="3" fill="#252626"/>
<rect x="51" y="1062" width="13" height="8" rx="3" fill="url(#led-shade)" pointer-events="none"/>
<rect id="led-mail" x="78" y="1062" width="13" height="8" rx="3" fill="#252626"/>
<rect x="78" y="1062" width="13" height="8" rx="3" fill="url(#led-shade)" pointer-events="none"/>
<g transform="translate(0 40)">
<rect x="145" y="130" width="570" height="790" rx="10" fill="#121416" stroke="#73797e" stroke-width="3"/>
<rect x="153" y="138" width="554" height="774" rx="5" fill="url(#bezel)"/>
</g>
<rect id="screen" x="165" y="195" width="525" height="700" fill="#c3c6c9"/>
<g transform="translate(0 40)">
<path d="M161 151 H694 M161 151 V858" fill="none" stroke="#62696d" stroke-opacity=".42" stroke-width="2"/>
''']
        parts.append(shortcut_strip("pda"))
        parts.append(text("CG Silicon", 204, 903, 11, fill="#a9b0b4"))
        parts.append("</g></svg>")
        return "\n".join(parts)

    if view not in ("laptop", "pda"):
        raise ValueError(f"unknown C700 view: {view}")
    return (laptop() if view == "laptop" else pda()) + "\n"


def build_sl6000(fonts):
    text = fonts.text_path
    parts = ['''<svg xmlns="http://www.w3.org/2000/svg" id="tosa" viewBox="0 40 800 1380" preserveAspectRatio="xMidYMin meet" role="group" aria-labelledby="title description">
<!--
  Original vector drawing of the Sharp Zaurus SL-6000 (Tosa).
  SPDX-FileCopyrightText: 2026 Koen Kooi
  SPDX-License-Identifier: CC-BY-SA-4.0
  Geometry informed by Sharp product images and device photographs.
  Printed lettering uses Open Sans outlines (SIL OFL 1.1).
  Sharp, Zaurus and CG Silicon are trademarks used to identify the device.
-->
<title id="title">Sharp Zaurus SL-6000</title>
<desc id="description">Front view of the black SL-6000 with a silver sliding QWERTY keyboard, a 480 by 640 VGA screen and no protective flip cover.</desc>
<view id="closed" viewBox="0 40 800 1380"/>
<view id="open" viewBox="0 40 800 1720"/>
<style>
  #close-keyboard { display: none }
  #open:target ~ #art #slider, #tosa[data-keyboard="open"] #slider { transform: translate(0, 340px) }
  #open:target ~ #art #open-keyboard, #tosa[data-keyboard="open"] #open-keyboard { display: none }
  #open:target ~ #art #close-keyboard, #tosa[data-keyboard="open"] #close-keyboard { display: inline }
</style>
<defs>
<linearGradient id="rim" x1="0" y1="0" x2="1" y2="0">
<stop stop-color="#4f585b"/><stop offset=".018" stop-color="#d5dde0"/><stop offset=".045" stop-color="#8f9b9f"/><stop offset=".08" stop-color="#4e575b"/><stop offset=".92" stop-color="#515b60"/><stop offset=".97" stop-color="#c5cfd3"/><stop offset="1" stop-color="#505a5e"/>
</linearGradient>
<linearGradient id="face" x1="0" y1="0" x2="1" y2=".3">
<stop stop-color="#41494b"/><stop offset=".06" stop-color="#2a3033"/><stop offset=".5" stop-color="#272c2f"/><stop offset=".92" stop-color="#242a2d"/><stop offset="1" stop-color="#41494c"/>
</linearGradient>
<linearGradient id="panel" x1="0" y1="0" x2=".15" y2="1">
<stop stop-color="#465158"/><stop offset=".12" stop-color="#353f45"/><stop offset=".65" stop-color="#242d32"/><stop offset="1" stop-color="#192126"/>
</linearGradient>
<linearGradient id="silver" x1="0" y1="0" x2=".8" y2="1">
<stop stop-color="#f0f2ed"/><stop offset=".4" stop-color="#d5d9d7"/><stop offset=".8" stop-color="#c1c8c7"/><stop offset="1" stop-color="#e4e8e3"/>
</linearGradient>
<linearGradient id="key-face" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#fffff8"/><stop offset=".15" stop-color="#e9ece5"/><stop offset=".82" stop-color="#ced3cb"/><stop offset="1" stop-color="#a7b0aa"/>
</linearGradient>
<linearGradient id="function-face" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#e5cbaa"/><stop offset=".22" stop-color="#ce9d72"/><stop offset=".8" stop-color="#ab7650"/><stop offset="1" stop-color="#916345"/>
</linearGradient>
<linearGradient id="button-face" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#56636c"/><stop offset=".2" stop-color="#414e56"/><stop offset=".8" stop-color="#273239"/><stop offset="1" stop-color="#151c20"/>
</linearGradient>
<linearGradient id="chrome" x1=".15" y1="0" x2=".85" y2="1">
<stop stop-color="#f4f8fa"/><stop offset=".08" stop-color="#9da8af"/><stop offset=".22" stop-color="#e3e9ec"/><stop offset=".4" stop-color="#535f67"/><stop offset=".54" stop-color="#1b242c"/><stop offset=".72" stop-color="#7e8d96"/><stop offset=".88" stop-color="#e1e8eb"/><stop offset="1" stop-color="#6b7880"/>
</linearGradient>
<radialGradient id="select-face" cx=".35" cy=".28" r=".75">
<stop stop-color="#9eaaaf"/><stop offset=".22" stop-color="#555f65"/><stop offset=".55" stop-color="#172027"/><stop offset=".86" stop-color="#10181e"/><stop offset="1" stop-color="#6e7c84"/>
</radialGradient>
<linearGradient id="led-shade" x1="0" y1="0" x2="1" y2="0">
<stop stop-color="#000" stop-opacity=".5"/><stop offset=".45" stop-color="#fff" stop-opacity=".3"/><stop offset=".8" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".5"/>
</linearGradient>
<pattern id="texture" width="7" height="6" patternUnits="userSpaceOnUse">
<path d="M1 1 h1 M4 4 h1" stroke="#fff" stroke-opacity=".027"/><path d="M3 2 h1 M6 5 h1" stroke="#000" stroke-opacity=".05"/>
</pattern>
<filter id="shadow" x="-10%" y="-8%" width="120%" height="120%"><feGaussianBlur stdDeviation="6"/></filter>
</defs>
<g id="art">
<path d="M56 96 Q56 68 84 68 H716 Q744 68 744 96 V1327 H56 Z" fill="url(#rim)" stroke="#4c575c" stroke-width="2"/>
<g id="keyboard">
<path d="M76 945 H724 V1330 H76 Z" fill="url(#silver)" stroke="#79868a" stroke-width="3"/>
<path d="M81 953 V1318 M719 953 V1318" stroke="#f8fcf8" stroke-width="3" opacity=".8"/>
''']

    def key(name, label, x, y, width=42, secondary="", function=False, shift=False):
        half = width / 2
        parts.append(f'<g id="key-{name}" aria-label="{escape(label if not shift else "Shift")}" transform="translate({x} {y})">')
        parts.append(f'<rect x="{-half-1}" y="-18" width="{width+2}" height="41" rx="6" fill="#798780"/>')
        fill = "function-face" if function else "key-face"
        parts.append(f'<rect x="{-half}" y="-20" width="{width}" height="39" rx="5" fill="url(#{fill})" stroke="#83918b" stroke-width="1.5"/>')
        parts.append(f'<path d="M{-half+5} -17 H{half-5}" stroke="#fff" stroke-opacity=".6" stroke-width="1.5"/>')
        if shift:
            parts.append('<path d="M-12 1 L0 -10 12 1 H7 V10 H-7 V1 Z" fill="none" stroke="#3b4543" stroke-width="2.2" stroke-linejoin="round"/>')
        elif name == "backspace":
            parts.append('<path d="M12 0 H-11 M-5 -6 L-12 0 -5 6" fill="none" stroke="#3b4543" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>')
        elif name == "enter":
            parts.append('<path d="M11 -7 V2 H-11 M-5 -4 L-12 2 -5 8" fill="none" stroke="#3b4543" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>')
        else:
            parts.append(text(label, 0, 6, 14 if len(label) > 1 else 18, fill="#3c4845"))
        parts.append("</g>")
        if secondary:
            parts.append(text(secondary, x, y - 27, 11, fill="#9b7c4c"))

    for i, char in enumerate("qwertyuiop"):
        key(char, char.upper(), 130 + i * 60, 1050, secondary="1234567890"[i])
    for i, char in enumerate("asdfghjkl"):
        key(char, char.upper(), 145 + i * 60, 1112, secondary="!@#$%&*()"[i])
    key("backspace", "←", 685, 1112, secondary="Del")
    key("shift-left", "", 130, 1174, shift=True)
    for i, char in enumerate("zxcvbnm"):
        key(char, char.upper(), 190 + i * 60, 1174,
            secondary={"x": "Cut", "c": "Copy", "v": "Paste"}.get(char, ""))
    key("comma-semicolon", ";", 610, 1174, secondary=",")
    key("shift-right", "", 670, 1174, shift=True)
    for name, label, x, width, second in (
        ("fn", "Fn", 130, 48, ""), ("tab", "Tab", 202, 48, "Caps"),
        ("slash", "/?", 274, 48, "Num"), ("space", "Space", 400, 155, "Symbol"),
        ("quote", "'\"", 530, 48, "~"), ("period", ".:", 602, 48, "<"),
        ("enter", "↵", 674, 48, ">"),
    ):
        key(name, label, x, 1236, width, second, function=name == "fn")
    parts += ['''</g>
<g id="slider">
<path d="M55 978 H745 L751 1365 Q751 1404 718 1406 H82 Q49 1404 49 1365 Z" fill="#000" opacity=".35" filter="url(#shadow)"/>
<path d="M58 976 H742 L747 1361 Q747 1396 716 1399 H84 Q53 1396 53 1361 Z" fill="url(#rim)" stroke="#535f65" stroke-width="3"/>
<path d="M70 982 H730 L735 1360 Q735 1386 712 1388 H88 Q65 1386 65 1360 Z" fill="url(#panel)" stroke="#111a20" stroke-width="2"/>
<path d="M70 982 H730 V1011 H70 Z" fill="#20292e"/>
<path d="M76 986 H724" stroke="#637178" stroke-opacity=".65" stroke-width="2"/>
<path d="M70 1012 H730" stroke="#131d23" stroke-width="2"/>
<path d="M72 1016 H728 L733 1358 Q733 1383 711 1385 H89 Q68 1383 67 1358 Z" fill="url(#texture)" pointer-events="none"/>
''']
    icons = {
        "calendar": '<rect x="-12" y="-10" width="24" height="20" rx="1"/><path d="M-12 -4 H12 M-4 -10 V10 M4 -10 V10 M-12 3 H12"/>',
        "contacts": '<circle cy="-6" r="5"/><path d="M-11 11 V5 Q0 -3 11 5 V11 Z"/>',
        "home": '<path d="M-14 -1 L0 -12 14 -1 M-10 -3 V11 H10 V-3 M-3 11 V3 H3 V11"/>',
        "menu": '<path d="M-13 -10 H7 V11 H-13 Z M-9 -5 H3 M-9 0 H3 M-9 5 H3 M12 -7 V8 M9 5 L12 9 15 5"/>',
        "mail": '<rect x="-14" y="-9" width="28" height="19" rx="1"/><path d="M-14 -8 L0 2 14 -8"/>',
    }

    def pill(name, x, y, width, height):
        parts.append(f'<g id="button-{name}" aria-label="{name}" transform="translate({x} {y})">')
        parts.append(f'<rect x="{-width/2-3}" y="{-height/2-2}" width="{width+6}" height="{height+5}" rx="{height/2}" fill="#151d22" stroke="#526169" stroke-width="2"/>')
        parts.append(f'<rect x="{-width/2}" y="{-height/2}" width="{width}" height="{height}" rx="{height/2-2}" fill="url(#button-face)" stroke="#142027" stroke-width="1.3"/>')
        parts.append(f'<path d="M{-width/2+12} {-height/2+3} H{width/2-12}" stroke="#86949c" stroke-opacity=".6" stroke-width="1.5"/>')

    for index, name in enumerate(("calendar", "contacts", "home", "menu", "mail")):
        pill(name, 170 + index * 115, 1047, 101, 36)
        parts.append(f'<g fill="none" stroke="#d4dce0" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">{icons[name]}</g></g>')
    pill("ok-secondary", 250, 1128, 99, 32)
    parts.append('<circle r="4.5" fill="#d7dfe3"/>')
    parts.append("</g>")
    pill("light", 580, 1128, 99, 32)
    parts.append('<path d="M-3 6 Q-3 3 -6 0 A8 8 0 1 1 6 0 Q3 3 3 6 Z M-3 9 H3 M-2 12 H2" fill="none" stroke="#cdd7dc" stroke-width="2.2" stroke-linejoin="round"/></g>')
    parts.append('<g id="mark-rotate" fill="none" stroke="#cad4da" stroke-width="2" transform="translate(665 1128)" pointer-events="none"><path d="M-14 -10 H-3 V1 H-14 Z M3 -1 H14 V10 H3 Z M-1 -13 Q13 -13 15 -2 M11 -6 L15 -2 17 -7"/></g>')
    for name, label, x in (("cancel", "Cancel", 180), ("ok", "OK", 620)):
        pill(name, x, 1225, 144, 39)
        parts.append(text(label, 0, 6, 16, fill="#e1e7ea"))
        parts.append("</g>")
    parts += ['''<g id="direction-pad" aria-label="Directional pad" transform="translate(400 1225)">
<circle r="106" fill="#152027" stroke="#4e5e67" stroke-width="2"/>
<circle r="99" fill="url(#chrome)" stroke="#c1ccd1" stroke-width="2"/>
<circle r="89" fill="url(#chrome)" stroke="#4a5963" stroke-width="1.5"/>
<path d="M-79 -33 A86 86 0 0 1 -21 -83 M22 83 A86 86 0 0 0 79 33" fill="none" stroke="#e4edf1" stroke-opacity=".6" stroke-width="5"/>
<g fill="#c6d1d6" stroke="#35434c" stroke-width="1"><rect x="-4" y="-79" width="8" height="4" rx="1"/><rect x="-4" y="75" width="8" height="4" rx="1"/><rect x="-79" y="-2" width="8" height="4" rx="1"/><rect x="71" y="-2" width="8" height="4" rx="1"/></g>
<circle r="48" fill="#26353d" stroke="#9eafb8" stroke-width="2"/>
<circle id="button-select" aria-label="Select" r="38" fill="url(#select-face)" stroke="#b7c7cf" stroke-width="2"/>
<path d="M-22 -16 Q-9 -31 10 -27" fill="none" stroke="#cfdae0" stroke-opacity=".5" stroke-width="3" pointer-events="none"/>
<path id="button-up" aria-label="Up" d="M-57 -71 Q0 -106 57 -71 L34 -42 Q0 -58 -34 -42 Z" fill="transparent" pointer-events="all"/>
<path id="button-right" aria-label="Right" d="M71 -57 Q106 0 71 57 L42 34 Q58 0 42 -34 Z" fill="transparent" pointer-events="all"/>
<path id="button-down" aria-label="Down" d="M-57 71 Q0 106 57 71 L34 42 Q0 58 -34 42 Z" fill="transparent" pointer-events="all"/>
<path id="button-left" aria-label="Left" d="M-71 -57 Q-106 0 -71 57 L-42 34 Q-58 0 -42 -34 Z" fill="transparent" pointer-events="all"/>
</g>
<a id="open-keyboard" href="#open" aria-label="Open keyboard"><title>Open keyboard</title><rect x="76" y="983" width="648" height="29" fill="transparent" pointer-events="all"/></a>
<a id="close-keyboard" href="#closed" aria-label="Close keyboard"><title>Close keyboard</title><rect x="76" y="983" width="648" height="29" fill="transparent" pointer-events="all"/></a>
</g>
<g id="casing">
<path d="M56 96 Q56 68 84 68 H716 Q744 68 744 96 V966 Q744 985 725 985 H75 Q56 985 56 966 Z" fill="url(#rim)" stroke="#505e64" stroke-width="2"/>
<path d="M68 97 Q68 80 85 80 H715 Q732 80 732 97 V962 Q732 973 720 973 H80 Q68 973 68 962 Z" fill="url(#face)" stroke="#101c23" stroke-width="2"/>
<path d="M71 99 Q71 83 87 83 H713 Q729 83 729 99 V960 Q729 970 718 970 H82 Q71 970 71 960 Z" fill="url(#texture)" pointer-events="none"/>
<path d="M82 84 H718 M71 99 V955" fill="none" stroke="#bdcbd0" stroke-opacity=".28" stroke-width="2"/>
<rect x="119" y="147" width="562" height="742" rx="6" fill="#151c20" stroke="#626e72" stroke-width="2"/>
<rect x="129" y="158" width="542" height="720" rx="2" fill="#080d11" stroke="#172125" stroke-width="2"/>
<rect id="screen" x="137.5" y="168" width="525" height="700" fill="#c3c6c9"/>
<path d="M134 163 H665 M134 163 V872" fill="none" stroke="#7f8e93" stroke-opacity=".25" stroke-width="2"/>
''']
    parts.append(text("SHARP", 400, 948, 23, face="bold", width=152, fill="#d8e0e3"))
    parts.append(text("CG Silicon", 194, 129, 12, fill="#b9c6cd"))
    for name, x in (("wlan", 489), ("bluetooth", 535), ("mail", 581), ("charge", 627)):
        parts.append(f'<rect x="{x-2}" y="87" width="13" height="27" rx="4" fill="#152029" stroke="#626f76" stroke-width="1.5"/>')
        parts.append(f'<rect id="led-{name}" aria-label="{name} indicator" x="{x}" y="89" width="9" height="23" rx="3" fill="#252626"/>')
        parts.append(f'<rect x="{x}" y="89" width="9" height="23" rx="3" fill="url(#led-shade)" pointer-events="none"/>')
    parts.append('''<g fill="none" stroke="#adbcc4" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" pointer-events="none">
<g id="mark-wlan" transform="translate(493.5 127)">
<path d="M-11 -3 A15.6 15.6 0 0 1 11 -3 M-7 1 A9.9 9.9 0 0 1 7 1 M-3 5 A4.25 4.25 0 0 1 3 5"/>
<circle cy="8" r="1.3" fill="#adbcc4" stroke="none"/>
</g>
<path id="mark-bluetooth" transform="translate(539.5 127)" d="M-5 -5 L5 5 0 9 V-9 L5 -5 -5 5"/>
<path id="mark-mail" transform="translate(585.5 127)" d="M-9 -6 H9 V6 H-9 Z M-9 -5 L0 2 9 -5"/>
<path id="mark-charge" transform="translate(631.5 127)" d="M-10 -4.5 H7 V4.5 H-10 Z M7 -1.5 H10 V1.5 H7"/>
</g>
<path d="M57 931 V965 M743 931 V965" stroke="#a9b5b8" stroke-width="5" opacity=".6"/>
</g>
</g>
</svg>
''')
    return "\n".join(parts)


def build_h2200_keyboard(fonts):
    text = fonts.text_path
    blue, orange, ink = "#304b74", "#b45d35", "#181b1e"
    parts = ['''<g id="addon-keyboard" role="group" aria-label="iPAQ clip-on thumb keyboard">
<defs>
<linearGradient id="kb-shell" x1="0" y1="0" x2="1" y2=".1">
<stop stop-color="#88877f"/><stop offset=".025" stop-color="#e5e2d9"/><stop offset=".07" stop-color="#b7b4aa"/><stop offset=".2" stop-color="#d7d4ca"/><stop offset=".7" stop-color="#c5c3bb"/><stop offset=".94" stop-color="#e8e7df"/><stop offset="1" stop-color="#999a94"/>
</linearGradient>
<linearGradient id="kb-finish" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#fff" stop-opacity=".3"/><stop offset=".35" stop-color="#fff" stop-opacity="0"/><stop offset=".83" stop-color="#000" stop-opacity=".04"/><stop offset="1" stop-color="#000" stop-opacity=".25"/>
</linearGradient>
<radialGradient id="kb-key" cx=".35" cy=".2" r=".9">
<stop stop-color="#fafbf6"/><stop offset=".38" stop-color="#e2e4de"/><stop offset=".78" stop-color="#c8cdc7"/><stop offset=".94" stop-color="#a1a8a2"/><stop offset="1" stop-color="#f0f3eb"/>
</radialGradient>
<linearGradient id="kb-orange" x1="0" y1="0" x2=".8" y2="1">
<stop stop-color="#f6ad4f"/><stop offset=".18" stop-color="#f58b27"/><stop offset=".8" stop-color="#cd5818"/><stop offset="1" stop-color="#a84818"/>
</linearGradient>
<linearGradient id="kb-blue" x1="0" y1="0" x2=".8" y2="1">
<stop stop-color="#78bad8"/><stop offset=".18" stop-color="#2788b5"/><stop offset=".8" stop-color="#075b89"/><stop offset="1" stop-color="#0c3f64"/>
</linearGradient>
<pattern id="kb-brush" width="5" height="3" patternUnits="userSpaceOnUse"><path d="M0 1 H4" stroke="#fff" stroke-opacity=".07"/></pattern>
<filter id="kb-shadow" x="-10%" y="-10%" width="120%" height="125%"><feGaussianBlur stdDeviation="4"/></filter>
</defs>
<path d="M17 872 C55 892 145 911 240 916 Q400 930 560 916 C655 911 745 892 783 872 L787 1238 Q787 1290 738 1304 Q400 1370 62 1304 Q13 1290 13 1238 Z" fill="#000" opacity=".3" filter="url(#kb-shadow)" transform="translate(0 5)"/>
<path d="M17 872 C55 892 145 911 240 916 Q400 930 560 916 C655 911 745 892 783 872 L787 1238 Q787 1290 738 1304 Q400 1370 62 1304 Q13 1290 13 1238 Z" fill="url(#kb-shell)" stroke="#85877f" stroke-width="3"/>
<path d="M17 872 C55 892 145 911 240 916 Q400 930 560 916 C655 911 745 892 783 872 L787 1238 Q787 1290 738 1304 Q400 1370 62 1304 Q13 1290 13 1238 Z" fill="url(#kb-finish)"/>
<path d="M26 889 C125 942 278 947 400 948 C522 947 675 942 774 889" fill="none" stroke="#6b706c" stroke-width="3"/>
<path d="M28 884 C135 934 278 940 400 941 C522 940 665 934 772 884" fill="none" stroke="#f7f7ed" stroke-opacity=".8" stroke-width="3"/>
<path d="M24 928 V1234 Q24 1278 68 1291 Q400 1354 732 1291 Q776 1278 776 1234 V928" fill="none" stroke="#fff" stroke-opacity=".25" stroke-width="4"/>
<path d="M31 952 Q400 1020 769 952 V1236 Q769 1275 728 1288 Q400 1348 72 1288 Q31 1275 31 1236 Z" fill="url(#kb-brush)" pointer-events="none"/>
''']

    def bowl(x, depth):
        return depth * (1 - ((x - 400) / 315) ** 2)

    def arrow(direction, x=0, y=0, size=1, fill=ink):
        angle = {"left": -90, "right": 90, "down": 180, "up": 0}[direction]
        return f'<path d="M0 -12 L-10 0 H-4 V11 H4 V0 H10 Z" transform="translate({x} {y}) rotate({angle}) scale({size})" fill="{fill}"/>'

    def key(name, label, x, y, alternate="", colour=None, direction=None):
        parts.append(f'<g id="key-{name}" aria-label="{escape(label or name)}" transform="translate({x:.3f} {y:.3f})">')
        parts.append('<ellipse cy="2" rx="29.5" ry="29" fill="#565b56"/><ellipse cy="1" rx="28" ry="27.5" fill="#1a201e"/>')
        parts.append(f'<ellipse rx="25.5" ry="26" fill="url(#{colour or "kb-key"})" stroke="#c7ccc3" stroke-width="1.5"/>')
        parts.append('<path d="M-19 -14 A24 24 0 0 1 11 -22" fill="none" stroke="#fff" stroke-opacity=".7" stroke-width="1.5"/>')
        if name == "tab":
            parts.append(f'<path d="M10 2 V10 H-10 M-3 4 L-10 10 -3 16" fill="none" stroke="{ink}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
        elif direction:
            parts.append(arrow(direction, 0, 9, .8))
        elif name == "shift":
            parts.append(text("Shift", 0, 14, 11, width=35, fill=ink))
            parts.append('<rect x="-16" y="-16" width="32" height="13" rx="1" fill="none" stroke="#b45d35" stroke-width="1.2"/>')
            parts.append(text("TEXT", 0, -6, 8, width=27, fill=orange))
        elif name == "control":
            parts.append(text("Ctrl", 0, 14, 12, width=28, fill=ink))
        elif colour:
            parts.append(text(label, 0, 7, 16, face="bold", fill="#f3f4df"))
        else:
            parts.append(text(label, 5 if alternate else 0, 15, 21, face="bold", width=22 if label == "M" else None, fill=ink))
        if alternate:
            parts.append(text(alternate, 0 if direction or name == "control" else -9, -5, 12 if len(alternate) > 1 else 16, face="bold", fill=orange))
        parts.append("</g>")

    for row, letters in enumerate(("QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM")):
        start = 85 if row < 2 else 155
        alternates = ("1234567890", "*/+-=~'\"@", "$()?!,.")
        for i, label in enumerate(letters):
            x = start + i * 70
            key(label.lower(), label, x, 980 + row * 79 + bowl(x, 30 - row * 2), alternates[row][i])
    key("backspace", "Backspace", 715, 1059, "Del", direction="left")
    key("fn-orange", "Fn", 85, 1138, colour="kb-orange")
    key("fn-blue", "Fn", 645, 1138 + bowl(645, 26), colour="kb-blue")
    key("tab", "Tab", 715, 1138, "Tab", direction="left")
    key("shift", "Shift", 100, 1218 + bowl(100, 23))
    key("left", "Left", 178, 1218 + bowl(178, 23), direction="left")
    key("right", "Right", 256, 1218 + bowl(256, 23), "cap", direction="right")
    key("down", "Down", 564, 1218 + bowl(564, 23), "\u20ac", direction="down")
    key("up", "Up", 642, 1218 + bowl(642, 23), "\u00a3", direction="up")
    key("control", "Control / Escape", 720, 1218 + bowl(720, 23), "Esc")
    parts.append('<g id="key-space" aria-label="Space" transform="translate(410 1243)">')
    parts.append('<rect x="-88" y="-29" width="176" height="58" rx="25" fill="#575e57" stroke="#e9ece2" stroke-width="2"/><rect x="-82" y="-24" width="164" height="49" rx="21" fill="url(#kb-key)" stroke="#777f77" stroke-width="1.5"/>')
    parts.append('<path d="M-65 -20 H65" stroke="#fff" stroke-opacity=".8" stroke-width="2"/>')
    parts.append(text("SPACE", 0, 8, 21, face="bold", width=106, fill=ink))
    parts.append("</g>")
    parts.append('<g transform="translate(178 1210) rotate(10)" fill="#b45d35"><path d="M-13 -6 L-1 -8 V2 L-13 4 Z M1 -8 L13 -10 V0 L1 2 Z M-13 7 L-1 5 V15 L-13 17 Z M1 5 L13 3 V13 L1 15 Z"/></g>')

    for row, labels in enumerate((("'", "`", "^", None, None, None, "", "&", "\\"),
                                  ("~", "\u00a8", "\u00b0", "%", "#", "\u00b7", "\u00a7", "\u00ed"),
                                  ("\u03bc", "\u00c7", "\u03b2", ">", "<", ";", "\u00fc", "\u00bf"))):
        for i, label in enumerate(labels):
            x = 120 + 70 * i
            y = 946 + row * 79 + bowl(x, 30 - row * 2)
            if label:
                parts.append(text(label, x, y, 18, fill=blue))
            elif row == 0 and i in (3, 4, 5):
                icon = {
                    3: '<rect x="-11" y="-9" width="22" height="18"/><path d="M-11 -3 H11 M-4 -9 V9 M4 -9 V9 M-11 3 H11"/>',
                    4: '<rect x="-11" y="-10" width="22" height="20"/><path d="M-3 -10 V10 M1 -5 H7 M1 0 H7 M1 5 H7"/>',
                    5: '<rect x="-12" y="-8" width="24" height="17"/><path d="M-12 -7 L0 2 12 -7"/>',
                }[i]
                parts.append(f'<g transform="translate({x} {y-8})" fill="none" stroke="{blue}" stroke-width="2">{icon}</g>')
    for label, x, y in (("\u00d1", 217, 1196), ("\u00f1", 295, 1207), ("OFF", 512, 1205),
                         ("P", 585, 1197), ("P", 663, 1187)):
        parts.append(text(label, x, y, 16, fill=blue))
    parts.append(arrow("down", 600, 1189, .45, blue))
    parts.append(arrow("up", 678, 1179, .45, blue))
    parts.append(text("iPAQ", 400, 1314, 20, face="bold", fill="#e1e3d8"))
    parts.append("</g>")
    return "\n".join(parts)


def build_camera(fonts=None, *, view="front"):
    """Orthographic 3D camera, retaining the original SVG text and SMIL timeline."""
    def value(number):
        return format(number, '.15g') if isinstance(number, (int, float)) else str(number)

    def number(number):
        return value(math.floor(number * 100 + .5) / 100)

    G = SimpleNamespace(bx0=0, bx1=300, by0=60, by1=323, footX1=355, footY0=284,
                        hx0=300, hx1=555, hy0=53, hy1=266, D=130, lx=437, ly=167,
                        R=92, L=100, px0=92, px1=336, py1=668, pz=6, ay=159.5)
    Z = G.D / 2
    D2R = math.pi / 180
    PHI = 55 if view == 'above' else 8
    DUR = 10
    NS = 'vector-effect="non-scaling-stroke"'
    FONT = 'font-family="Futura, \'Century Gothic\', \'Avenir Next\', \'Trebuchet MS\', sans-serif"'

    def frontT(c, a):
        ca, sa = math.cos(a), math.sin(a)
        return G.ay * (1 - ca) - c * sa, ca

    def sideT(c, a):
        ca, sa = math.cos(a), math.sin(a)
        return G.ay + (c - G.ay) * ca, -sa

    def tstr(transform):
        ty, scale = transform
        return f'translate(0 {number(ty)}) scale(1 {number(scale)})'

    def thetaAt(t):
        ease = lambda s: (1 - math.cos(math.pi * s)) / 2
        if t <= 1:
            return 0
        if t <= 5:
            return 180 * ease((t - 1) / 4)
        if t <= 6.5:
            return 180
        if t <= 9.5:
            return 180 * (1 - ease((t - 6.5) / 3))
        return 0

    times = [0] + [1 + 4 * i / 28 for i in range(29)] + [6.5 + 3 * i / 21 for i in range(22)] + [DUR]
    keyTimes = ';'.join(number(t / DUR) for t in times)

    def shadeRaw(normal):
        return .8 * (.62 - (normal[0] * -.7 + normal[1] * .71))

    def shadeOp(normal):
        base = shadeRaw((math.sin(PHI * D2R), math.cos(PHI * D2R)))
        return max(0, min(.3, shadeRaw(normal) - max(0, base)))

    NORMAL = {
        'front': lambda a: (-math.sin(a), math.cos(a)),
        'back': lambda a: (math.sin(a), -math.cos(a)),
        'top': lambda a: (-math.cos(a), -math.sin(a)),
        'bottom': lambda a: (math.cos(a), math.sin(a)),
    }

    def headPlane(kind, c, content, theta, vis=None, shade=None):
        transform = frontT if kind == 'front' else sideT
        if theta is not None:
            a = (theta - PHI) * D2R
            if vis and not vis(a):
                return ''
            overlay = f'{shade[0]} fill="#000" opacity="{number(shadeOp(NORMAL[shade[1]](a)))}"/>' if shade else ''
            return f'<g transform="{tstr(transform(c, a))}">{content}{overlay}</g>'
        tr, sc, vv, op = [], [], [], []
        for time in times:
            a = (thetaAt(time) - PHI) * D2R
            ty, scale = transform(c, a)
            tr.append('0 ' + number(ty))
            sc.append('1 ' + number(scale))
            if vis:
                vv.append('visible' if vis(a) else 'hidden')
            if shade:
                op.append(number(shadeOp(NORMAL[shade[1]](a))))
        a0 = -PHI * D2R
        ty0, s0 = transform(c, a0)
        rep = f'dur="{DUR}s" repeatCount="indefinite" keyTimes="{keyTimes}"'
        if shade:
            content += f'{shade[0]} fill="#000" opacity="{op[0]}"><animate attributeName="opacity" {rep} values="{";".join(op)}"/></rect>'
        visAttr, visAnim = '', ''
        if vis:
            initial = 'visible' if vis(a0) else 'hidden'
            visAttr = f' visibility="{initial}"'
            visAnim = f'<animate attributeName="visibility" calcMode="discrete" {rep} values="{";".join(vv)}"/>'
        return (f'<g{visAttr} transform="translate(0 {number(ty0)})">{visAnim}'
            f'<animateTransform attributeName="transform" type="translate" {rep} values="{";".join(tr)}"/>'
            f'<g transform="scale(1 {number(s0)})"><animateTransform attributeName="transform" type="scale" {rep} values="{";".join(sc)}"/>'
                + content + '</g></g>')

    def staticPlane(kind, c, content, a):
        transform = frontT if kind == 'front' else sideT
        return f'<g transform="{tstr(transform(c, a))}">{content}</g>'


    def defs():
        return (f'''<defs>
<linearGradient id="gBody" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d5cfc3"/><stop offset=".55" stop-color="#c2bbae"/><stop offset="1" stop-color="#a9a296"/></linearGradient>
<linearGradient id="gBodyH" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#6f6858" stop-opacity=".28"/><stop offset=".07" stop-color="#fff" stop-opacity=".18"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#5a5446" stop-opacity=".16"/></linearGradient>
<linearGradient id="gHead" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d9d3c7"/><stop offset=".6" stop-color="#c6bfb2"/><stop offset="1" stop-color="#b0a99c"/></linearGradient>
<linearGradient id="gHeadH" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#5a5446" stop-opacity=".22"/><stop offset=".05" stop-color="#fff" stop-opacity=".15"/><stop offset=".85" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#5a5446" stop-opacity=".2"/></linearGradient>
<linearGradient id="gTop" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#c3bcb0"/><stop offset="1" stop-color="#e2ddd3"/></linearGradient>
<linearGradient id="gTopB" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#c7c0b3"/><stop offset=".25" stop-color="#ddd8cd"/><stop offset="1" stop-color="#e4dfd5"/></linearGradient>
<linearGradient id="gIpaq" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d3d4d1"/><stop offset=".15" stop-color="#c3c4c1"/><stop offset="1" stop-color="#b3b4b1"/></linearGradient>
<linearGradient id="gUnder" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#a8a090"/><stop offset="1" stop-color="#8f8778"/></linearGradient>
<radialGradient id="gDish" cx=".7" cy=".45" r=".8"><stop offset="0" stop-color="#d3cdc1"/><stop offset=".6" stop-color="#c3bcaf"/><stop offset="1" stop-color="#9d968a"/></radialGradient>
<linearGradient id="gWall" gradientUnits="userSpaceOnUse" x1="{value(G.lx - G.R)}" y1="0" x2="{value(G.lx + G.R)}" y2="0"><stop offset="0" stop-color="#7f786a"/><stop offset=".3" stop-color="#e2dccf"/><stop offset=".55" stop-color="#cfc8b9"/><stop offset=".85" stop-color="#9d9586"/><stop offset="1" stop-color="#7a7365"/></linearGradient>
<radialGradient id="gRing" cx=".4" cy=".35" r=".75"><stop offset="0" stop-color="#f1ede4"/><stop offset=".7" stop-color="#cfc8ba"/><stop offset="1" stop-color="#a59d8e"/></radialGradient>
<radialGradient id="gGlass" cx=".42" cy=".38" r=".7"><stop offset="0" stop-color="#3a3a3c"/><stop offset=".6" stop-color="#18181a"/><stop offset="1" stop-color="#0b0b0c"/></radialGradient>
<radialGradient id="gPupil" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#b0362a"/><stop offset=".55" stop-color="#5c1712"/><stop offset="1" stop-color="#1a0b0a"/></radialGradient>
<linearGradient id="gPlate" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f4f2ec"/><stop offset=".45" stop-color="#cfcac0"/><stop offset=".55" stop-color="#e9e6df"/><stop offset="1" stop-color="#bdb8ad"/></linearGradient>
<linearGradient id="gPlug" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#262628"/><stop offset=".4" stop-color="#18181a"/><stop offset="1" stop-color="#0f0f10"/></linearGradient>
<linearGradient id="gBodyEdge" x1="0" y1="0" x2=".25" y2="1"><stop stop-color="#f3eee4"/><stop offset=".12" stop-color="#bdb6a9"/><stop offset=".72" stop-color="#a69e90"/><stop offset=".94" stop-color="#777064"/><stop offset="1" stop-color="#5e594f"/></linearGradient>
<linearGradient id="gHeadEdge" x1="0" y1="0" x2=".15" y2="1"><stop stop-color="#f4f0e7"/><stop offset=".13" stop-color="#c7bfb1"/><stop offset=".76" stop-color="#b1a99b"/><stop offset="1" stop-color="#696257"/></linearGradient>
<radialGradient id="gBarrelSeat" cx=".48" cy=".45" r=".55"><stop offset=".72" stop-color="#777165"/><stop offset=".88" stop-color="#8a8376"/><stop offset="1" stop-color="#c9c2b5" stop-opacity="0"/></radialGradient>
<clipPath id="cHead"><rect x="{value(G.hx0)}" y="{value(G.hy0)}" width="{value(G.hx1 - G.hx0)}" height="{value(G.hy1 - G.hy0)}" rx="12"/></clipPath>
<clipPath id="cLogo"><circle cx="0" cy="0" r="31"/></clipPath>
</defs>''')


    def bodyFrontPath(inset=0):
        bx0, bx1 = G.bx0 + inset, G.bx1 - inset
        by0, by1 = G.by0 + inset, G.by1 - inset
        footX1, footY0 = G.footX1 - inset, G.footY0 + inset
        r, rt, rf = max(14-inset, 2), max(6-inset, 2), max(9-inset, 2)
        return (f'''M{value(bx0 + r)} {value(by0)}H{value(bx1 - rt)}Q{value(bx1)} {value(by0)} {value(bx1)} {value(by0 + rt)}V{value(footY0-5)}Q{value(bx1)} {value(footY0)} {value(bx1+5)} {value(footY0)}H{value(footX1 - rf)}''' +
        f'''Q{value(footX1)} {value(footY0)} {value(footX1)} {value(footY0 + rf)}V{value(by1 - rf)}Q{value(footX1)} {value(by1)} {value(footX1 - rf)} {value(by1)}''' +
        f'''H{value(bx0 + r)}Q{value(bx0)} {value(by1)} {value(bx0)} {value(by1 - r)}V{value(by0 + r)}Q{value(bx0)} {value(by0)} {value(bx0 + r)} {value(by0)}Z''')


    def hpLogo(cx, cy):
        return (f'''<g transform="translate({value(cx)} {value(cy)})"><circle r="31" fill="#1f3c88"/>''' +
        f'''<g clip-path="url(#cLogo)"><g transform="skewX(-18)" fill="none" stroke="#f4f4f4" stroke-width="5.2" stroke-linecap="butt">''' +
        f'''<path d="M-13 -34V19M-13 -1Q-13 -9 -4 -9Q3 -9 3 -2V19"/>''' +
        f'''<path d="M11 -8V36M11 -3Q11 -9 18 -9Q26 -9 26 3Q26 15 18 15Q11 15 11 9"/></g></g>''' +
        f'''<circle r="31" fill="none" stroke="#0f2457" stroke-width=".8"/></g>''')


    def bodyFront():
        by0 = G.by0
        bx, by, bw, bh = 78, 120, 128, 82
        return (f'''<path id="bodyFace" d="{value(bodyFrontPath())}" fill="url(#gBodyEdge)" stroke="#857d6d" stroke-width="1" {value(NS)}/>''' +
        f'''<path d="{value(bodyFrontPath(4))}" fill="url(#gBody)"/>''' +
        f'''<path d="{value(bodyFrontPath(4))}" fill="url(#gBodyH)"/>''' +
        f'''<path d="M{value(G.bx1-1)} {value(G.by0+8)}V{value(G.footY0-6)}Q{value(G.bx1-1)} {value(G.footY0+1)} {value(G.bx1+6)} {value(G.footY0+1)}H{value(G.footX1-10)}" fill="none" stroke="#514b42" stroke-width="1.4" {value(NS)}/>''' +
        f'''<path d="M{value(G.bx1+5)} {value(G.footY0+5)}H{value(G.footX1-10)}" stroke="#f3eee4" stroke-opacity=".75" stroke-width="1.2" {value(NS)}/>''' +
        f'''<rect id="bodyTextArea" x="{value(G.bx0)}" y="{value(by0)}" width="{value(G.bx1 - G.bx0)}" height="{value(G.by1 - by0)}" fill="none"/>''' +
        f'''<rect x="{value(bx)}" y="{value(by)}" width="{value(bw)}" height="{value(bh)}" rx="7" fill="#9c9484"/>''' +
        f'''<rect x="{value(bx + 1.5)}" y="{value(by + 1.5)}" width="{value(bw - 3)}" height="{value(bh - 3)}" rx="6" fill="#b1a999"/>''' +
        f'''<rect x="{value(bx + 5)}" y="{value(by + 5)}" width="{value(bw - 10)}" height="{value(bh - 10)}" rx="4" fill="url(#gPlate)" stroke="#8e8676" stroke-width=".8" {value(NS)}/>''' +
        hpLogo(bx + bw / 2, by + bh / 2) +
        f'''<text data-in="bodyTextArea" x="51" y="248.4" {value(FONT)} font-size="29" fill="#2e2b25" stroke="#c4bdb0" stroke-width=".7" textLength="201" lengthAdjust="spacingAndGlyphs"><tspan font-weight="bold">hp</tspan> photosmart</text>''' +
        f'''<text data-in="bodyTextArea" x="51" y="284" {value(FONT)} font-size="29" fill="#2e2b25" stroke="#c4bdb0" stroke-width=".7" textLength="214" lengthAdjust="spacingAndGlyphs">mobile camera</text>''')


    def plugPath():
        px0, px1, py1 = G.px0, G.px1, G.py1
        top, notchY, inset, cut = G.by1 - 12, 558, 11, 32
        return (f'''M{value(px0)} {value(top)}H{value(px1)}V{value(py1 - 5)}Q{value(px1)} {value(py1)} {value(px1 - 5)} {value(py1)}H{value(px0 + inset + cut)}''' +
        f'''L{value(px0 + inset)} {value(py1 - cut)}V{value(notchY + 6)}L{value(px0)} {value(notchY - 4)}Z''')


    def plugFront():
        cx = (G.px0 + G.px1) / 2
        return (f'''<path id="plugFace" d="{value(plugPath())}" fill="url(#gPlug)" stroke="#000" stroke-width="1" {value(NS)}/>''' +
        f'''<path d="M{value(G.px0 + 3)} {value(G.by1)}V552" stroke="#3b3b3e" stroke-width="1.4" {value(NS)}/>''' +
        f'''<g fill="#86868a"><path d="M{value(cx - 80)} 342h14l-7 9z"/><path d="M{value(cx + 66)} 342h14l-7 9z"/></g>''' +
        f'''<text data-in="plugFace" x="{value(cx)}" y="353" text-anchor="middle" font-family="'Arial Narrow', 'Helvetica Neue', Arial, sans-serif" font-weight="bold" font-size="18" fill="#86868a" textLength="62" lengthAdjust="spacingAndGlyphs">PUSH</text>''' +
        f'''<text data-in="plugFace" x="135" y="428" {value(FONT)} font-size="44" fill="#d6d6d6" textLength="162" lengthAdjust="spacingAndGlyphs">1.3 MP</text>''' +
        f'''<rect x="131.5" y="449.5" width="170" height="3.2" fill="#3f55b5"/>''' +
        f'''<text data-in="plugFace" x="156" y="504" {value(FONT)} font-size="31" fill="#cfcfcf" textLength="135" lengthAdjust="spacingAndGlyphs">4x digital</text>''' +
        f'''<text data-in="plugFace" x="212" y="538" {value(FONT)} font-size="31" fill="#cfcfcf" textLength="69" lengthAdjust="spacingAndGlyphs">zoom</text>''' +
        f'''<text data-in="plugFace" x="233" y="641" font-family="'Arial Black', 'Helvetica Neue', Arial, sans-serif" font-weight="900" font-style="italic" font-size="27" fill="#ededed" textLength="62" lengthAdjust="spacingAndGlyphs">SD</text>''' +
        f'''<path d="M297 626q8 3 6 9" fill="none" stroke="#ededed" stroke-width="2.4"/>''')


    def focusMarks():
        lx, ly, r = G.lx, G.ly, G.R + 12
        def pt(degrees):
            return lx + r * math.cos(degrees * D2R), ly + r * math.sin(degrees * D2R)
        def arc(a0, a1):
            x0, y0 = pt(a0)
            x1, y1 = pt(a1)
            return f'M{number(x0)} {number(y0)}A{r} {r} 0 0 {1 if a1 > a0 else 0} {number(x1)} {number(y1)}'
        def head(degrees, direction):
            x, y = pt(degrees)
            tangent = (degrees + 90 * direction) * D2R
            tx, ty = math.cos(tangent), math.sin(tangent)
            nx, ny = -ty, tx
            return f'M{number(x + tx * 6)} {number(y + ty * 6)}L{number(x + nx * 3.5)} {number(y + ny * 3.5)}L{number(x - nx * 3.5)} {number(y - ny * 3.5)}Z'
        def icon(x, y, inner):
            return f'<g transform="translate({x} {y})"><rect x="-7" y="-7" width="14" height="14" rx="1.5" fill="#efeae0" stroke="#1d1b17" stroke-width="1.1" {NS}/>{inner}</g>'
        tulip = f'''<path d="M-4 -4l2 2l2-3l2 3l2-2v3q0 3-4 3q-4 0-4-3z M0 2v3.5" fill="#1d1b17" stroke="#1d1b17" stroke-width=".8"/>'''
        mount = f'''<path d="M-5.5 4.5l3.5-6l2 3l2-4.5l3.5 7.5z" fill="#1d1b17"/>'''
        return (f'''<g fill="none" stroke="#1d1b17" stroke-width="1.3" {value(NS)}><path d="{value(arc(-28, -52))}"/><path d="{value(arc(28, 52))}"/></g>''' +
        f'''<g fill="#1d1b17"><path d="{value(head(-52, -1))}"/><path d="{value(head(52, 1))}"/></g>''' +
        icon(543, 66, tulip) + icon(543, 253, mount))


    def headFrontFace():
        hx0, hx1, hy0, hy1, lx, ly, R = G.hx0, G.hx1, G.hy0, G.hy1, G.lx, G.ly, G.R
        return (f'''<rect x="{hx0}" y="{hy0}" width="{hx1-hx0}" height="{hy1-hy0}" rx="12" fill="url(#gHeadEdge)" stroke="#857d6d" stroke-width="1" {NS}/>''' +
        f'''<rect x="{hx0+3.5}" y="{hy0+3.5}" width="{hx1-hx0-7}" height="{hy1-hy0-7}" rx="9" fill="url(#gHead)"/>''' +
        f'''<rect x="{hx0+3.5}" y="{hy0+3.5}" width="{hx1-hx0-7}" height="{hy1-hy0-7}" rx="9" fill="url(#gHeadH)"/>''' +
        f'''<g clip-path="url(#cHead)"><circle cx="{lx}" cy="{ly+2}" r="{R+13}" fill="url(#gBarrelSeat)"/><circle cx="{lx}" cy="{ly}" r="{R+5}" fill="#bdb5a7" stroke="#8c8578" stroke-width=".8" {NS}/></g>''' +
        f'''<path d="M{hx0+3} {hy0+13}Q{hx0+3} {hy0+3} {hx0+13} {hy0+3}H{hx1-13}Q{hx1-3} {hy0+3} {hx1-3} {hy0+13}" fill="none" stroke="#faf5eb" stroke-opacity=".7" stroke-width="1.2" {NS}/>''' +
        focusMarks())


    def headBackFace():
        hx0, hx1, hy0, hy1 = G.hx0, G.hx1, G.hy0, G.hy1
        cx, cy = hx0 + .47 * (hx1 - hx0), G.ay
        return (f'''<rect x="{hx0}" y="{hy0}" width="{hx1-hx0}" height="{hy1-hy0}" rx="12" fill="url(#gHeadEdge)" stroke="#857d6d" stroke-width="1" {NS}/><rect x="{hx0+3.5}" y="{hy0+3.5}" width="{hx1-hx0-7}" height="{hy1-hy0-7}" rx="9" fill="url(#gHead)"/>''' +
        f'''<g clip-path="url(#cHead)"><circle cx="{value(number(cx))}" cy="{value(number(cy))}" r="104" fill="url(#gDish)" stroke="#a49c8c" stroke-width=".8" {value(NS)}/></g>''' +
        f'''<rect x="{hx0+3.5}" y="{hy0+3.5}" width="{hx1-hx0-7}" height="{hy1-hy0-7}" rx="9" fill="url(#gHeadH)"/>''')


    def headSideFace(fill):
        hx0, hx1 = G.hx0, G.hx1
        return (f'''<rect x="{hx0}" y="{-Z}" width="{hx1-hx0}" height="{G.D}" rx="12" fill="url(#gHeadEdge)" stroke="#857d6d" stroke-width="1" {NS}/>''' +
        f'''<rect x="{hx0+3}" y="{-Z+3}" width="{hx1-hx0-6}" height="{G.D-6}" rx="9" fill="{fill}"/>''' +
        f'''<path d="M{hx0+8} 0H{hx1-8}" stroke="#5f584a" stroke-width=".85" {NS}/><path d="M{hx0+8} 1.5H{hx1-8}" stroke="#e8e2d7" stroke-opacity=".65" stroke-width=".8" {NS}/>''' +
        f'''<path d="M{hx0+3} {Z-13}Q{hx0+3} {Z-3} {hx0+13} {Z-3}H{hx1-13}Q{hx1-3} {Z-3} {hx1-3} {Z-13}" fill="none" stroke="#f5f0e6" stroke-opacity=".6" stroke-width="1" {NS}/>''')


    def barrelBase():
        return f'''<ellipse cx="{value(G.lx)}" cy="{value(G.ly)}" rx="{value(G.R)}" ry="{value(G.R)}" fill="url(#gWall)"/>'''

    def barrelWall():
        return f'''<rect x="{value(G.lx - G.R)}" y="{value(Z)}" width="{value(2 * G.R)}" height="{value(G.L)}" fill="url(#gWall)"/>'''

    def barrelCap():
        lx, ly, R = G.lx, G.ly, G.R
        return (f'''<circle cx="{value(lx)}" cy="{value(ly)}" r="{value(R)}" fill="url(#gRing)" stroke="#7d7667" stroke-width="1" {value(NS)}/>''' +
        f'''<circle cx="{value(lx)}" cy="{value(ly)}" r="{value(R - 3)}" fill="none" stroke="#f6f3ec" stroke-width="1" {value(NS)} opacity=".7"/>''' +
        f'''<circle cx="{value(lx)}" cy="{value(ly)}" r="67" fill="#b9b2a3" stroke="#4f493e" stroke-width="1" {value(NS)}/>''' +
        f'''<circle cx="{value(lx)}" cy="{value(ly)}" r="58" fill="url(#gGlass)"/>''' +
        f'''<circle cx="{value(lx)}" cy="{value(ly)}" r="25" fill="#101012" stroke="#2c2c2f" stroke-width="1" {value(NS)}/>''' +
        f'''<circle cx="{value(lx)}" cy="{value(ly + 1)}" r="11" fill="url(#gPupil)"/>''' +
        f'''<ellipse cx="{value(lx - 22)}" cy="{value(ly - 26)}" rx="12" ry="6" fill="#fff" opacity=".13" transform="rotate(-35 {value(lx - 22)} {value(ly - 26)})"/>''')


    FACE_OV = f'''<rect x="{value(G.hx0)}" y="{value(G.hy0)}" width="{value(G.hx1 - G.hx0)}" height="{value(G.hy1 - G.hy0)}" rx="12"'''

    SIDE_OV = f'''<rect x="{value(G.hx0)}" y="{value(-Z)}" width="{value(G.hx1 - G.hx0)}" height="{value(G.D)}" rx="12"'''

    def headCore(theta):
        # The rounded solid closes the bevel junctions between projected faces.
        def profile(angle):
            c, s = abs(math.cos(angle)), abs(math.sin(angle))
            height = (G.hy1-G.hy0) * c + G.D * s
            return G.ay-height/2, height, 12*(c+s)
        y, height, radius = profile(((theta or 0)-PHI) * D2R)
        result = (f'<rect id="head-core" x="{G.hx0}" y="{number(y)}" width="{G.hx1-G.hx0}" '
                  f'height="{number(height)}" rx="12" ry="{number(radius)}" fill="url(#gHeadEdge)">')
        if theta is None:
            values = [profile((thetaAt(t)-PHI) * D2R) for t in times]
            for index, attribute in enumerate(("y", "height", "ry")):
                samples = ";".join(number(item[index]) for item in values)
                result += (f'<animate attributeName="{attribute}" dur="{DUR}s" repeatCount="indefinite" '
                           f'keyTimes="{keyTimes}" values="{samples}"/>')
        return result + "</rect>"

    def headAssembly(theta):
        zc = Z + G.L
        front = lambda a: math.cos(a) > 0
        back = lambda a: math.cos(a) <= 0
        top = lambda a: math.sin(a) < 0
        bot = lambda a: math.sin(a) >= 0
        def barrel(vis):
            collar = f'<circle cx="{G.lx}" cy="{G.ly}" r="{G.R+3}" fill="url(#gWall)" stroke="#7d7667" stroke-width=".8" {NS}/>'
            return (headPlane('front', Z, collar, theta, vis)
                    + headPlane('front', Z+4, barrelBase(), theta, vis)
                    + headPlane('side', G.ly, barrelWall(), theta, vis))
        return ('<g id="headAssembly">' + headCore(theta)
                + barrel(back)
                + headPlane('side', G.hy0, headSideFace('url(#gTop)'), theta, top, (SIDE_OV, 'top'))
                + headPlane('side', G.hy1, headSideFace('url(#gTop)'), theta, bot, (SIDE_OV, 'bottom'))
                + headPlane('front', -Z, headBackFace(), theta, back, (FACE_OV, 'back'))
                + headPlane('front', Z, headFrontFace(), theta, front, (FACE_OV, 'front'))
                + barrel(front)
                + headPlane('front', zc, barrelCap(), theta, front)
                + '</g>')


    def bodySweep(a):
        ca, sa = math.cos(a), math.sin(a)
        def P(x, y, z):
            return f'{number(x)} {number(G.ay + (y - G.ay) * ca - z * sa)}'
        def A(r, x, y, z):
            return f'A{r} {number(r * ca)} 0 0 1 {P(x, y, z)}'
        bx0, bx1, by0, by1, footX1, footY0 = G.bx0, G.bx1, G.by0, G.by1, G.footX1, G.footY0
        b, fz = -Z, Z
        d = (f'''M{value(P(bx0, by0 + 14, b))}{value(A(14, bx0 + 14, by0, b))}L{value(P(bx1 - 4, by0, b))}{value(A(4, bx1, by0 + 4, b))}''' +
        f'''L{value(P(bx1, footY0, b))}L{value(P(footX1 - 7, footY0, b))}{value(A(7, footX1, footY0 + 7, b))}''' +
        f'''L{value(P(footX1, by1 - 7, fz))}{value(A(7, footX1 - 7, by1, fz))}L{value(P(bx0 + 14, by1, fz))}{value(A(14, bx0, by1 - 14, fz))}Z''')
        seam = (f'''M{value(P(bx0 + 5, by0, 0))}L{value(P(bx1, by0, 0))}M{value(P(bx1, footY0, 0))}L{value(P(footX1 - 3, footY0, 0))}''')
        return (f'''<path d="{value(d)}" fill="url(#gTopB)" stroke="#857d6d" stroke-width="1"/>''' +
        f'''<path d="{value(seam)}" stroke="#6f6858" stroke-width="1" fill="none"/>''')


    def staticParts(a, extra='', noPlug=False):
        return ('' if noPlug else staticPlane('front', G.pz, plugFront(), a)) + extra + bodySweep(a) + staticPlane('front', Z, bodyFront(), a)


    aS = -PHI * D2R
    a = aS
    VB = '-24 -30 610 720'

    HEADER = f'''<!--
  SPDX-FileCopyrightText: 2026 Koen Kooi
  SPDX-License-Identifier: CC-BY-SA-4.0

  Provenance: original vector drawing of the HP Photosmart Mobile Camera
  (1.3 MP, 4x digital zoom, SD-sized plug), made from SVG geometry and
  gradients after the owner's photographs of his own unit; no photograph is
  embedded. The head is projected from a simple 3D model (box head, cylinder
  barrel) rotating about its swivel axis. "hp" and "SD" are trademarks of
  their owners; the badge and the SD mark are simplified drawings.
  Rounded housing edges and barrel seating were checked against the owner's
  close-ups and "HP PhotoSmart SDIO Kamera.jpg" by Afrank99, Wikimedia Commons.
  No reference photograph is traced or embedded.
-->'''

    def svgDoc(viewBox, w, h, title, desc, body):
        return (f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="{value(viewBox)}" width="{value(w)}" height="{value(h)}" role="img" aria-labelledby="t d">
<title id="t">{value(title)}</title>
<desc id="d">{value(desc)}</desc>
{value(HEADER)}
{value(defs())}
{value(body)}
</svg>
''')


    if view == 'front':
        return svgDoc(VB, 610, 720,
      'HP Photosmart Mobile Camera, front view',
      'The champagne-silver HP Photosmart Mobile Camera for the iPAQ h2200, seen from the front and slightly above: the body with the hp badge and the words hp photosmart mobile camera, the swivelling head on the right with its cylindrical lens barrel and the focus marks, and the black SD-card shaped plug below that reads PUSH, 1.3 MP, 4x digital zoom and SD.',
      staticParts(aS) + headAssembly(0))

    if view == 'away':
        return svgDoc(VB, 610, 720,
      'HP Photosmart Mobile Camera, head turned away',
      'The same camera with its head swivelled half a turn about the axis that runs from the body into the head: the lens barrel now points away from the viewer and the head shows its plain back with a shallow round dish.',
      staticParts(aS) + headAssembly(180))

    if view == 'swivel':
        return svgDoc(VB, 610, 720,
      'HP Photosmart Mobile Camera, swivelling head',
      'Animation, 10 second loop: the head of the camera, carrying the lens barrel and the focus marks, turns half a turn about its swivel axis, so the lens tips up, points away and shows the plain back of the head, then turns back. The body and the plug stay still.',
      staticParts(aS) + headAssembly(None))

    if view == 'above':
        return svgDoc('-24 30 610 340', 610, 340,
        'HP Photosmart Mobile Camera, seen from above',
        'The camera seen from above and in front: the top faces of the body and the head with the seam between them and the shell seam along their tops, the lens barrel standing out of the head as a cylinder, and the badge and name foreshortened on the front of the body.',
        staticParts(a, '', True) + headAssembly(0))

    raise ValueError(f"unknown camera view: {view}")


@dataclass(frozen=True)
class CameraPose:
    """Measured SD seating point for camera coordinate (214, 340).

    Rotation is in SVG degrees about that point; foreshorten projects camera
    depth onto the rear keyboard plane. Poses describe physical placement
    only, not electrical or software compatibility.
    """

    x: float
    y: float
    scale: float
    rotation: float = 0
    layer: str = "behind"
    evidence: str = ""
    foreshorten: float = 1

    def matrix(self):
        if (not all(math.isfinite(value) for value in
                    (self.x, self.y, self.scale, self.rotation, self.foreshorten))
                or self.scale <= 0 or self.foreshorten <= 0 or self.layer not in ("behind", "front")):
            raise ValueError("invalid camera pose")
        angle = math.radians(self.rotation)
        a = self.scale * math.cos(angle)
        b = self.scale * math.sin(angle)
        c, d = -b * self.foreshorten, a * self.foreshorten
        return a, b, c, d, self.x - a * 214 - c * 340, self.y - b * 214 - d * 340

    def transform(self):
        # Extra precision keeps distant rotated corners aligned with their bounds.
        return "matrix(" + " ".join(format(value, ".12g") for value in self.matrix()) + ")"

    def bounds(self):
        a, b, c, d, e, f = self.matrix()
        points = [(a*x+c*y+e, b*x+d*y+f) for x in (-24, 586) for y in (-30, 690)]
        return (min(x for x, y in points), min(y for x, y in points),
                max(x for x, y in points), max(y for x, y in points))


def sd_scale(case_units, case_mm):
    """The camera's 244-unit stem represents a standard 24 mm SD card."""
    return case_units / case_mm * 24 / 244


# Slot edges are source-verified; seating points and projection are photo estimates.
# Widths: iPAQ 77 mm; SL-5500/5600 74 mm; SL-6000 79.8 mm (Sharp guide p100);
# C700 119 x 83 mm (HPC.ru review). h2200 retains the owner's established pose.
CAMERA_POSES = {
    "h2200": CameraPose(370, 26, 1.08, evidence="Owner photos; original on-h2200 camera composition."),
    "h3900": CameraPose(414, 36, sd_scale(776.2 * .875, 77),
                       evidence="HP h3900 QuickSpecs p1 item15: top SD slot, near midline."),
    "h5550": CameraPose(408, 80, sd_scale(776.9 * .875, 77),
                       evidence="HP h5550 QuickSpecs p1 item18: slot spans x416-522 on a body spanning x294-650; centre about 49% across."),
    "hx4700": CameraPose(368, 29, sd_scale(2176 * 525 / 1776, 77),
                        evidence="HP hx4700 user guide p144 (11-2): top slot, about 45% across front."),
    "hx2700": CameraPose(361, 108, sd_scale(1304 * 525 / 923, 76.6),
                        evidence="hx2110 back photo (Wikimedia, Litvinenko): SD above CF on top, about 4 mm left of centre from the front."),
    "sl-5500": CameraPose(56, 730, sd_scale(704, 74), rotation=-90,
                         evidence="Sharp SL-5500 Start-up Guide printed pp20,63: front-left long edge."),
    "sl-5600": CameraPose(56, 530, sd_scale(704, 74), rotation=-90,
                         evidence="Sharp SL5600 brochure (2003), p2 callout1: front-left edge, screen mid-height."),
    "sl-6000": CameraPose(565, 68, sd_scale(688, 79.8),
                         evidence="Sharp SL-6000 guide pp28,78: SD beside CF on top short edge."),
    "sl-c700-pda": CameraPose(44, 629, sd_scale(716, 83), rotation=-90,
                             evidence="HPC.ru /lib/arts/1927/ and ok.jpg: left hinge edge, about 55% down."),
    "sl-c700-laptop": CameraPose(630, 823, sd_scale(1092, 119), foreshorten=.25,
                                evidence="HPC.ru /lib/arts/1927/: rear base edge, behind upright display and hinge."),
}


@dataclass(frozen=True)
class Model:
    """Builder: Fonts -> SVG text; path: repository-relative.

    Optional slider metadata is (root_id, open_height, travel) for the
    shared 800-wide sliding Zaurus frame convention.
    """

    path: str
    build: Optional[Callable[[Fonts], str]]
    screen: Optional[tuple]
    fonts: tuple
    slider: tuple = ()
    source: str = ""
    camera: str = ""
    camera_pose: Optional[CameraPose] = None
    keyboard: bool = False


MODELS = {
    "h3900": Model("h3900/h3900-framed-template.svg", build_h3900,
                  (137.5, 244.75, 525, 700), ("Mukta_Regular.ttf", "OpenSans_BoldItalic.ttf")),
    "h5550": Model("h5550/h5550-framed-template.svg", build_h5550,
                  (137.5, 244.75, 525, 700), ("Roboto_Bold.ttf", "Roboto_Regular.ttf")),
    "hx4700": Model("hx4700/hx4700-framed-template.svg", build_hx4700,
                   (137.5, 244.75, 525, 700), ("OpenSans_Bold.ttf",)),
    "hx2700": Model("hx2700/hx2700-framed-template.svg", build_hx2700,
                   (137.5, 244.75, 525, 700), ("OpenSans_Bold.ttf",)),
    "sl-5500": Model("sl-5500/sl-5500-framed-template.svg", build_sl5500,
                    (137.5, 168, 525, 700), ("OpenSans_Regular.ttf", "OpenSans_Bold.ttf"),
                    ("collie", 1670, 290)),
    "sl-5600": Model("sl-5600/sl-5600-framed-template.svg", build_sl5600,
                    (137.5, 168, 525, 700), ("OpenSans_Regular.ttf", "OpenSans_Bold.ttf"),
                    ("poodle", 1750, 370)),
    "sl-6000": Model("sl-6000/sl-6000-framed-template.svg", build_sl6000,
                    (137.5, 168, 525, 700), ("OpenSans_Regular.ttf", "OpenSans_Bold.ttf"),
                    ("tosa", 1720, 340)),
    "sl-c700-laptop": Model("sl-c700/sl-c700-laptop.svg", partial(build_c700, view="laptop"),
                           (255, 92, 700, 525),
                           ("OpenSans_Regular.ttf", "OpenSans_Bold.ttf", "NotoSansCJKjp_Regular.otf")),
    "sl-c700-pda": Model("sl-c700/sl-c700-pda.svg", partial(build_c700, view="pda"),
                        (165, 195, 525, 700), ("OpenSans_Regular.ttf", "OpenSans_Bold.ttf")),
}
CAMERA_MODELS = {
    "camera-" + view: Model(
        "hp-photosmart-camera/hp-photosmart-camera" + ("" if view == "front" else "-" + view) + ".svg",
        partial(build_camera, view=view), None, ())
    for view in ("front", "away", "swivel", "above")
}
MANUAL_MODELS = {
    "h2200": Model("h2200/ipaq-h2200.svg", None, (137.5, 168, 525, 700), (),
                  source="h2200/ipaq-h2200.svg"),
}
ALIASES = {
    "sl-c700": ("sl-c700-laptop", "sl-c700-pda"),
    "all": tuple(MODELS),
    "camera": tuple(CAMERA_MODELS),
}


LOCAL_URL = re.compile(r"""url\(\s*(['"]?)#([A-Za-z_][\w:.-]*)\1\s*\)""")


def namespace_ids(root, prefix):
    """Rename an accessory's IDs and local URL, CSS, href and SMIL references."""
    ids = [node.get("id") for node in root.iter() if node.get("id")]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate IDs in accessory")
    mapping = {identity: prefix + identity for identity in ids}
    alternatives = "|".join(re.escape(identity) for identity in sorted(mapping, key=len, reverse=True))
    fragment = re.compile(r"#(" + alternatives + r")(?![\w-])") if mapping else None
    event = re.compile(r"(?<![\w:.-])(" + alternatives + r")(?=\.[A-Za-z_])") if mapping else None

    def references(value):
        return fragment.sub(lambda match: "#" + mapping[match[1]], value) if fragment else value

    for node in root.iter():
        for key, value in list(node.attrib.items()):
            local = key.split("}")[-1]
            if local == "id":
                value = mapping[value]
            elif local in ("aria-labelledby", "aria-describedby", "data-in"):
                value = " ".join(mapping.get(identity, identity) for identity in value.split())
            else:
                value = references(value)
                if local in ("begin", "end") and event:
                    value = event.sub(lambda match: mapping[match[1]], value)
            node.set(key, value)
        if node.tag == f"{{{SVG_NS}}}style" and node.text:
            node.text = references(node.text)
    return root


def expanded_viewbox(viewbox, bounds):
    x, y, width, height = viewbox
    left, top, right, bottom = bounds
    x0, y0 = min(x, left - 20), min(y, top - 20)
    x1, y1 = max(x + width, right + 20), max(y + height, bottom + 20)
    return tuple(float(fmt3(value)) for value in (x0, y0, x1 - x0, y1 - y0))


def viewbox_text(viewbox):
    return " ".join(fmt3(value) for value in viewbox)


def compose_keyboard(drawing, fonts):
    """Attach the supplied h2200 keyboard drawing to its manual frame."""
    root = ET.fromstring(drawing, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    component = ET.fromstring(f'<svg xmlns="{SVG_NS}">{build_h2200_keyboard(fonts)}</svg>')[0]
    source_ids = {node.get("id") for node in root.iter() if node.get("id")}
    keyboard_ids = {node.get("id") for node in component.iter() if node.get("id")}
    if source_ids & keyboard_ids:
        raise ValueError("keyboard IDs collide with the manual frame")
    root.append(component)
    root.set("viewBox", "0 0 800 1400")
    root.set("data-keyboard-accessory", "attached")
    ET.register_namespace("", SVG_NS)
    return ET.tostring(root, encoding="unicode") + "\n"


def open_keyboard(drawing, slider):
    """Default a sliding frame to open, including in static SVG renderers."""
    root = ET.fromstring(drawing, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    root_id, _, travel = slider
    opened = root.find(f"{{{SVG_NS}}}view[@id='open']")
    panel = root.find(f".//{{{SVG_NS}}}g[@id='slider']")
    style = root.find(f"{{{SVG_NS}}}style")
    if opened is None or panel is None or style is None:
        raise ValueError("open keyboard requires a sliding frame with fragment controls")
    root.set("viewBox", opened.get("viewBox"))
    root.set("data-keyboard", "open")
    panel.set("transform", f"translate(0 {travel})")
    style.text = (style.text or "") + f'''
#closed:target ~ #art #slider, #{root_id}[data-keyboard="closed"] #slider {{ transform: translate(0, 0px) }}
#closed:target ~ #art #open-keyboard, #{root_id}[data-keyboard="closed"] #open-keyboard {{ display: inline }}
#closed:target ~ #art #close-keyboard, #{root_id}[data-keyboard="closed"] #close-keyboard {{ display: none }}
'''
    ET.register_namespace("", SVG_NS)
    return ET.tostring(root, encoding="unicode") + "\n"


def compose_camera(drawing, view, pose):
    """Add a generated camera without wrapping or renaming device controls."""
    if view not in ("front", "away", "swivel") or pose is None:
        raise ValueError("camera composition requires an explicit view and measured pose")
    def parse(text):
        return ET.fromstring(text, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))

    root = parse(drawing)
    camera = namespace_ids(parse(build_camera(view=view)), "photosmart-")
    camera_ids = {node.get("id") for node in camera.iter() if node.get("id")}
    device_ids = {node.get("id") for node in root.iter() if node.get("id")}
    if (camera_ids | {"photosmart-camera"}) & device_ids:
        raise ValueError("device IDs collide with the camera namespace")
    group = ET.Element(f"{{{SVG_NS}}}g", {
        "id": "photosmart-camera", "transform": pose.transform(), "role": "img",
        "aria-labelledby": camera.get("aria-labelledby"),
    })
    group.extend(list(camera))
    if pose.layer == "front":
        root.append(group)
    else:
        metadata = {"title", "desc", "defs", "style", "view", "metadata"}
        position = next((i for i, child in enumerate(root)
                         if isinstance(child.tag, str) and child.tag.split("}")[-1] not in metadata), len(root))
        root.insert(position, group)
    title = root.find(f"{{{SVG_NS}}}title")
    if title is None:
        identity = "frame-camera-title"
        if identity in device_ids:
            raise ValueError("device ID collides with composition title")
        title = ET.Element(f"{{{SVG_NS}}}title", {"id": identity})
        title.text = "Handheld with HP Photosmart Mobile Camera"
        root.insert(0, title)
        root.set("role", "img")
        root.set("aria-labelledby", identity)
    else:
        title.text = (title.text or "Handheld") + " with HP Photosmart Mobile Camera"
    original = tuple(float(value) for value in root.get("viewBox").split())
    expanded = expanded_viewbox(original, pose.bounds())
    root.set("viewBox", viewbox_text(expanded))
    root.set("data-camera", view)
    for dimension, index in (("width", 2), ("height", 3)):
        if dimension in root.attrib:
            css_size = float(root.get(dimension)) * expanded[index] / original[index]
            root.set(dimension, str(round(css_size)))
    for fragment in root.findall(f"{{{SVG_NS}}}view"):
        base = tuple(float(value) for value in fragment.get("viewBox").split())
        fragment.set("viewBox", viewbox_text(expanded_viewbox(base, pose.bounds())))
    ET.register_namespace("", SVG_NS)
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    return ET.tostring(root, encoding="unicode") + "\n"


def validate_svg(drawing, model):
    """Check the generated document, not a pre-existing artwork snapshot."""
    root = ET.fromstring(drawing)
    if root.tag != f"{{{SVG_NS}}}svg":
        raise ValueError("document root is not an SVG")
    viewbox = tuple(float(value) for value in root.get("viewBox", "").split())
    if (len(viewbox) != 4 or not all(math.isfinite(value) for value in viewbox)
            or viewbox[2] <= 0 or viewbox[3] <= 0):
        raise ValueError("invalid SVG viewBox")
    ids = {}
    for element in root.iter():
        identity = element.get("id")
        if identity is not None:
            if not identity or identity in ids:
                raise ValueError(f"empty or duplicate SVG ID: {identity!r}")
            ids[identity] = element
    screen = ids.get("screen")
    for element in root.iter():
        for key, value in element.attrib.items():
            references = [match[2] for match in LOCAL_URL.finditer(value)]
            if key.split("}")[-1] == "href" and value.startswith("#"):
                references.append(value[1:])
            if key in ("aria-labelledby", "aria-describedby", "data-in"):
                references.extend(value.split())
            if any(reference not in ids for reference in references):
                raise ValueError(f"unresolved local SVG reference in {key}={value!r}")
        if element.tag == f"{{{SVG_NS}}}style":
            if any(match[2] not in ids for match in LOCAL_URL.finditer(element.text or "")):
                raise ValueError("unresolved local SVG reference in stylesheet")
        if element.tag in (f"{{{SVG_NS}}}animate", f"{{{SVG_NS}}}animateTransform"):
            times = tuple(float(value) for value in element.get("keyTimes", "").split(";") if value)
            values = element.get("values", "").split(";")
            if (len(times) < 2 or len(times) != len(values) or times[0] != 0 or times[-1] != 1
                    or not all(math.isfinite(value) and 0 <= value <= 1 for value in times)
                    or any(a > b for a, b in zip(times, times[1:]))):
                raise ValueError("invalid SVG animation timeline")
    if model.screen is None:
        if screen is not None:
            raise ValueError("standalone accessory must not contain a screen")
        return root
    if screen is None or screen.tag != f"{{{SVG_NS}}}rect":
        raise ValueError("missing screen rectangle")
    geometry = tuple(float(screen.get(key, "nan")) for key in ("x", "y", "width", "height"))
    if geometry != model.screen:
        raise ValueError(f"screen geometry mismatch: {geometry}, expected {model.screen}")
    parents = {child: parent for parent in root.iter() for child in parent}
    ancestor = screen
    while ancestor is not None:
        if ancestor.get("transform"):
            raise ValueError("screen or its ancestor has a transform")
        ancestor = parents.get(ancestor)
    if model.slider:
        root_id, open_height, travel = model.slider
        expected = (0, 40, 800, open_height if model.keyboard else 1380)
        if model.camera:
            expected = expanded_viewbox(expected, model.camera_pose.bounds())
        if root.get("id") != root_id or viewbox != expected:
            raise ValueError("invalid sliding frame root")
        for name, height in (("open", open_height), ("closed", 1380)):
            view = ids.get(name)
            expected = (0, 40, 800, height)
            if model.camera:
                expected = expanded_viewbox(expected, model.camera_pose.bounds())
            if (view is None or view.tag != f"{{{SVG_NS}}}view"
                    or tuple(map(float, view.get("viewBox", "").split())) != expected):
                raise ValueError(f"invalid #{name} fragment view")
        for name, target in (("open-keyboard", "#open"), ("close-keyboard", "#closed")):
            link = ids.get(name)
            if link is None or link.get("href") != target:
                raise ValueError(f"invalid #{name} slider link")
        if "slider" not in ids or "keyboard" not in ids:
            raise ValueError("missing slider or keyboard")
        if model.keyboard and (root.get("data-keyboard") != "open"
                               or ids["slider"].get("transform") != f"translate(0 {travel})"):
            raise ValueError("keyboard variant must start with the slider open")
        css = "".join("".join(root.itertext()).split())
        rule = (f'#open:target~#art#slider,#{root_id}[data-keyboard="open"]#slider'
                f'{{transform:translate(0,{travel}px)}}')
        if rule not in css:
            raise ValueError("missing open slider CSS transform")
    if model.camera:
        camera = ids.get("photosmart-camera")
        if (model.camera_pose is None or root.get("data-camera") != model.camera or camera is None
                or camera.get("transform") != model.camera_pose.transform()):
            raise ValueError("missing or incorrect camera composition")
        left, top, right, bottom = model.camera_pose.bounds()
        if (viewbox[0] > left or viewbox[1] > top
                or viewbox[0] + viewbox[2] < right or viewbox[1] + viewbox[3] < bottom):
            raise ValueError("camera lies outside the expanded canvas")
    if model.keyboard and model.source:
        keyboard = ids.get("addon-keyboard")
        expected = (0, 0, 800, 1400)
        if model.camera:
            expected = expanded_viewbox(expected, model.camera_pose.bounds())
        if (keyboard is None or keyboard not in list(root) or keyboard.get("transform")
                or root.get("data-keyboard-accessory") != "attached" or viewbox != expected
                or sum(identity.startswith("key-") for identity in ids) != 37):
            raise ValueError("invalid h2200 clip-on keyboard composition")
    if model.keyboard and not (model.source or model.slider) and root.get("id") != "c700-laptop":
        raise ValueError("keyboard mode requires an open slider, C700 laptop or h2200 add-on")
    for name in ("led-mail", "led-charge"):
        if name in ids and (not ids[name].get("fill") or "url(" in ids[name].get("fill")):
            raise ValueError(f"#{name} must have a directly editable fill")
    return root


def select_models(names, camera=None, keyboard=False):
    selected = {}
    available = {**MODELS, **CAMERA_MODELS, **MANUAL_MODELS}
    for name in names:
        keys = ALIASES.get(name, (name,))
        if name == "all":
            if keyboard:
                keys = tuple(key for key, model in MODELS.items()
                             if model.slider or key == "sl-c700-laptop") + ("h2200",)
            elif camera:
                keys += tuple(MANUAL_MODELS)
        for key in keys:
            if key not in available:
                raise ValueError(f"unknown model: {key}; use --list")
            if keyboard and key in ("sl-c700-laptop", "sl-c700-pda"):
                key = "sl-c700-laptop"
            model = available[key]
            if model.source and not (camera or keyboard):
                raise ValueError(f"{key} is a manual source; select --camera or --keyboard to compose it")
            if keyboard:
                if not (model.slider or key in ("h2200", "sl-c700-laptop")):
                    raise ValueError(f"{key}: no supported keyboard mode")
                base = Path(model.path)
                model = replace(model, keyboard=True,
                                path=str(base.with_name(f"{base.stem}-keyboard.svg")),
                                fonts=("OpenSans_Regular.ttf", "OpenSans_Bold.ttf") if model.source else model.fonts)
            if camera:
                if camera not in ("front", "away", "swivel"):
                    raise ValueError(f"unknown camera view: {camera}")
                if model.screen is None:
                    raise ValueError("cannot attach a camera to a standalone accessory")
                if key not in CAMERA_POSES:
                    raise ValueError(f"{key}: no researched SD-slot camera pose; composition is unavailable")
                if key == "h2200" and not keyboard:
                    suffix = "" if camera == "front" else "-" + camera
                    path = f"hp-photosmart-camera/on-h2200{suffix}.svg"
                else:
                    base = Path(model.path)
                    path = str(base.with_name(f"{base.stem}-camera-{camera}.svg"))
                model = replace(model, path=path, camera=camera, camera_pose=CAMERA_POSES[key])
            selected[key] = model
    if not selected:
        raise ValueError("select a model or 'all'; use --list")
    return selected


def generate(selected, font_directory):
    """Build and validate the entire selection before any output is written."""
    drawings = {}
    required = sorted({filename for model in selected.values() for filename in model.fonts})
    with Fonts(font_directory) if required else nullcontext(None) as fonts:
        for filename in required:
            fonts.load(filename)
        for name, model in selected.items():
            drawing = ((REPOSITORY / model.source).read_text(encoding="utf-8")
                       if model.source else model.build(fonts))
            validate_svg(drawing, replace(model, camera="", camera_pose=None, keyboard=False))
            if model.keyboard:
                if model.source:
                    drawing = compose_keyboard(drawing, fonts)
                elif model.slider:
                    drawing = open_keyboard(drawing, model.slider)
            if model.camera:
                drawing = compose_camera(drawing, model.camera, model.camera_pose)
            validate_svg(drawing, model)
            drawings[name] = drawing.encode("utf-8")
    return drawings


def write_outputs(selected, drawings, paths):
    """Stage and verify every SVG, then atomically replace each destination."""
    staged = {}
    try:
        for name, destination in paths.items():
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.is_dir():
                raise IsADirectoryError(f"output is a directory: {destination}")
            stage = destination.with_name(f".{destination.name}.{uuid4().hex}.pending")
            staged[name] = stage
            with stage.open("xb") as output:
                output.write(drawings[name])
            data = stage.read_bytes()
            if data != drawings[name]:
                raise OSError(f"staged output differs: {destination}")
            validate_svg(data, selected[name])
        for name, destination in paths.items():
            os.replace(staged[name], destination)
        for name, destination in paths.items():
            data = destination.read_bytes()
            if data != drawings[name]:
                raise OSError(f"written output differs: {destination}")
            validate_svg(data, selected[name])
            print(f"Wrote {destination}", flush=True)
    finally:
        for stage in staged.values():
            stage.unlink(missing_ok=True)


def main(argv=None):
    status = 1
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("models", nargs="*", metavar="MODEL",
                            help="model names, sl-c700 (both views), or all")
        parser.add_argument("--list", action="store_true", help="list supported models and paths")
        output = parser.add_mutually_exclusive_group()
        output.add_argument("--output-dir", type=Path,
                            help="output tree root (default: directory containing this script)")
        output.add_argument("--output", "-o", type=Path, help="exact .svg path; requires one view")
        parser.add_argument("--fonts", type=Path,
                            default=Path(os.environ.get("IPAQ_FONTS", "/Library/Fonts")),
                            help="font directory (default: IPAQ_FONTS or /Library/Fonts)")
        parser.add_argument("--check", action="store_true",
                            help="regenerate and compare exact bytes at the output paths; do not write")
        parser.add_argument("--camera", choices=("front", "away", "swivel"),
                            help="compose a camera using a researched SD-slot pose; variant paths only")
        parser.add_argument("--keyboard", action="store_true",
                            help="open a Zaurus slider, select C700 laptop mode or attach the h2200 keyboard; combines with --camera")
        args = parser.parse_args(argv)
        if args.list:
            if args.models or args.output or args.output_dir or args.check or args.camera or args.keyboard:
                raise ValueError("--list cannot be combined with generation options")
            for name, model in {**MODELS, **CAMERA_MODELS}.items():
                print(f"{name:16} {model.path}")
            print("sl-c700          both C700 views\nall              all generated handheld views")
            print("camera           all four standalone camera views")
            print("h2200            manual source; compose with --camera and/or --keyboard")
            print("Camera poses: " + ", ".join(CAMERA_POSES))
        else:
            selected = select_models(args.models, args.camera, args.keyboard)
            if args.output and (len(selected) != 1 or args.output.suffix.lower() != ".svg"):
                raise ValueError("--output requires exactly one view and a .svg filename")
            if args.output:
                name, model = next(iter(selected.items()))
                available = {**MODELS, **CAMERA_MODELS, **MANUAL_MODELS}
                reserved = {Path(item.path).name for item in available.values()}
                for item in (*MODELS.values(), *MANUAL_MODELS.values()):
                    stem = Path(item.path).stem
                    reserved.add(f"{stem}-keyboard.svg")
                    for view in ("front", "away", "swivel"):
                        reserved.add(f"{stem}-camera-{view}.svg")
                        reserved.add(f"{stem}-keyboard-camera-{view}.svg")
                reserved.update(f"on-h2200{suffix}.svg" for suffix in ("", "-away", "-swivel"))
                own_stem = Path(available[name].path).stem + ("-keyboard" if args.keyboard else "")
                own_name = own_stem + (f"-camera-{args.camera}" if args.camera else "") + ".svg"
                if args.output.name in reserved and args.output.name not in (Path(model.path).name, own_name):
                    raise ValueError(f"{args.output.name} is reserved for another model or variant")
            if args.output and args.camera:
                model = next(iter(selected.values()))
                if (not args.output.name.endswith(f"-camera-{args.camera}.svg")
                        and args.output.name != Path(model.path).name):
                    raise ValueError(f"--camera output must end in -camera-{args.camera}.svg "
                                     "or use the model's default variant filename")
            if args.output and args.keyboard:
                suffix = "-keyboard" + (f"-camera-{args.camera}" if args.camera else "") + ".svg"
                if not args.output.name.endswith(suffix):
                    raise ValueError(f"--keyboard output must end in {suffix}")
            base = args.output_dir if args.output_dir is not None else REPOSITORY
            paths = {name: args.output if args.output is not None else base / model.path
                     for name, model in selected.items()}
            drawings = generate(selected, args.fonts)
            if args.check:
                for name, path in paths.items():
                    existing = path.read_bytes()
                    validate_svg(existing, selected[name])
                    if existing != drawings[name]:
                        raise ValueError(f"{path}: differs from regenerated SVG")
                    print(f"Matches {path}", flush=True)
            else:
                write_outputs(selected, drawings, paths)
        status = 0
    except SystemExit as error:
        status = 0 if error.code == 0 else 1
    except (Exception, KeyboardInterrupt) as error:
        print(f"Error: {error or type(error).__name__}", file=sys.stderr, flush=True)
    finally:
        print("SUCCESS" if status == 0 else "FAILURE", flush=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
