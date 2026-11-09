#!/usr/bin/env python3
"""Generate the iPAQ h3900 framed-screenshot template SVG.

usage: venv/bin/python gen_h3900_wide.py OUT.svg [--debug-outline]

This is gen_h3900_v2.py with the body outline and the record housing
re-measured (2026-11-08, frames-new/h3900-wide/notes.md): the owner's front
photo photos/front-owner.jpg rectified by fitting the four edges of the screen
opening (tools/rectify.py) and cross-checked against tape-landscape.jpg. The
body is symmetric about BX, 16 photo px right of the screen centre CX; the cap,
pad, buttons and wordmarks stay where v2 put them (the photo shows them on CX).

The rest of the geometry is measured on photos/front-rect.png, the owner's front photo
rectified so that the screen opening is an upright 3:4 rectangle (see
measure/rectify.py). All coordinates below are in that image's pixels ("photo
px") and are drawn inside a group that maps them to SVG units at 0.875 units
per photo px, i.e. 2.1875 units per screen pixel, the scale of the h2200
drawings. The canvas follows the h2200 files: viewBox x offset -0.3125, width
800.625 units (366 CSS px), glass at x=137.5 so it lands on whole CSS pixels.

--debug-outline writes only the key outlines as red strokes, for overlaying on
the rectified photo (measure/overlay.py).
"""
import os
import sys
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen

# ---- canvas and mapping ----------------------------------------------------
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
BODY_HALF = [
    (0, 77), (150, 76.5), (245, 72.5), (280, 75.8), (310, 79.8), (330, 82.6), (350, 86),
    (370, 90), (381, 94), (388.5, 100.5), (391.5, 110), (392.3, 125), (390.3, 300),
    (388.6, 400), (387.3, 600), (387, 800), (385, 1000), (383.3, 1100), (381.1, 1200),
    (379.5, 1220), (377, 1236), (371.5, 1246), (362, 1255.5), (350, 1265), (330, 1278.5), (310, 1292.5),
    (270, 1316), (230, 1337), (190, 1353.5), (150, 1369.5), (110, 1379.3), (60, 1386.8),
    (0, 1389.6),
]
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
FONTS = os.environ.get('IPAQ_FONTS', '/Library/Fonts/')
WORDS = [
    ('iPAQ', 'Mukta_Regular.ttf', 24, 280, 246, 'start', '#2a2b2c', None),
    ('Pocket PC', 'Mukta_Regular.ttf', 21, 859, 243, 'end', '#2a2b2c', 129),
    ('COMPAQ', 'OpenSans_BoldItalic.ttf', 24, CAPX, 72, 'middle', '#f1f2f3', 169),
]
# -----------------------------------------------------------------------------


def f(v):
    s = f'{v:.2f}'.rstrip('0').rstrip('.')
    return '0' if s == '-0' else s


def pts(seq):
    return ' '.join(f'{f(x)},{f(y)}' for x, y in seq)


def mirror(half, cx):
    """Closed outline from a right-half profile listed top to bottom."""
    right = [(cx + h, y) for h, y in half]
    left = [(cx - h, y) for h, y in reversed(half) if h != 0]
    return right + left


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


def outline_paths():
    return {'body': spline(body_outline()), 'record': spline(RECORD_PTS, tension=6.0),
            'cap': spline(cap_outline(), tension=6.0)}


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


def word_path(text, font_file, cap_target, x, y, anchor, width_target):
    """Outline `text`; uniform scale from the cap height unless a width is given."""
    font = TTFont(FONTS + font_file)
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    cap = font['OS/2'].sCapHeight or font['head'].unitsPerEm * 0.7
    names = [cmap[ord(c)] for c in text]
    adv = [font['hmtx'][n][0] for n in names]
    bp = BoundsPen(gs)
    pen_x = 0
    for n, a in zip(names, adv):
        gs[n].draw(TransformPen(bp, (1, 0, 0, 1, pen_x, 0)))
        pen_x += a
    xmin, _, xmax, _ = bp.bounds
    ky = cap_target / cap
    kx = width_target / (xmax - xmin) if width_target else ky
    ink_w = (xmax - xmin) * kx
    left = {'start': x, 'end': x - ink_w, 'middle': x - ink_w / 2}[anchor] - xmin * kx
    pen = SVGPathPen(gs, ntos=f)
    pen_x = 0
    for n, a in zip(names, adv):
        gs[n].draw(TransformPen(pen, (kx, 0, 0, -ky, left + pen_x * kx, y)))
        pen_x += a
    return pen.getCommands()


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


def build(debug=False):
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

    if debug:
        red = 'fill="none" stroke="#ff2020" stroke-width="2"'
        rings = ''.join(f'<circle cx="{x}" cy="{y}" r="{RING_R}" {red}/>' for x, y, _ in BUTTONS)
        return (head + group +
                f'<path d="{body}" {red}/><path d="{record}" {red}/><path d="{cap}" {red}/>'
                f'<rect x="{o1[0]}" y="{o1[1]}" width="{o1[2] - o1[0]}" height="{o1[3] - o1[1]}" {red}/>'
                f'<ellipse cx="{n["cx"]}" cy="{n["cy"]}" rx="{n["ring"][0]}" ry="{n["ring"][1]}" {red}/>'
                f'<ellipse cx="{n["cx"]}" cy="{n["cy"]}" rx="{n["pad"][0]}" ry="{n["pad"][1]}" {red}/>'
                f'{rings}<circle cx="{POWER[0]}" cy="{POWER[1]}" r="31" {red}/>'
                f'<circle cx="{WINDOW[0]}" cy="{WINDOW[1]}" r="{WINDOW[2]}" {red}/>'
                + ''.join(f'<path d="{word_path(*w[:6], w[7])}" fill="#ff2020" fill-opacity="0.6"/>' for w in WORDS)
                + '</g></svg>\n')

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
    <stop offset="0" stop-color="#5d6064"/><stop offset="0.45" stop-color="#a7abaf"/><stop offset="1" stop-color="#6a6d71"/>
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
      <path d="{led_l}" fill="url(#ip-led-l)"/><path d="{led_r}" fill="url(#ip-led-r)"/>
      <path d="{led_l}" fill="url(#ip-led-v)"/><path d="{led_r}" fill="url(#ip-led-v)"/>
      <path d="{led_hl_l}" fill="none" stroke="#fff" stroke-opacity="0.55" stroke-width="1.6" stroke-linecap="round"/>
      <path d="{led_hl_r}" fill="none" stroke="#fff" stroke-opacity="0.55" stroke-width="1.6" stroke-linecap="round"/>
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


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) != 1:
        sys.exit('usage: gen_h3900_v2.py OUT.svg [--debug-outline]')
    with open(args[0], 'w') as fh:
        fh.write(build(debug='--debug-outline' in sys.argv))
    print('wrote', args[0])
