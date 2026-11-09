#!/usr/bin/env python3
"""Generate the HP iPAQ h5550 framed-screenshot template SVG (final redraw on the h3900 envelope).

usage: python gen_h5550_final3.py OUT.svg [--debug-outline]

Coordinates are "generator px" (gp), the same system as the h3900 drawing:
a group maps them to SVG units at 0.875 units per gp, with the glass at
(275,262)-(875,1062) gp = <rect id="screen"> x=137.5 y=244.75 525x700 units.

Body (owner, 2026-11-08): the h5550 and the h3900 have the same body (HP: 84
tapering to 77 mm wide, 133 vs 134 mm long; same expansion sleeves). The body
outline is therefore the corrected h3900 drawing's envelope
(frames-new/h3900-wide/gen_h3900_wide.py: BX, BODY_HALF, bottom curve), and
the canvas is that drawing's. Everything inside and around it comes from the
owner's photograph of his h5550 (owner-photo-20261108.jpg), rectified so that
its grey glass lies on the glass rect (tools/rectify_owner.py; measurement
only, nothing of the photograph is used in the output). In that photograph
the body is wider and longer relative to the glass than the envelope allows,
so photo positions are mapped onto the envelope:
  my(): the band and glass stay; outside the band the photo is scaled by one
        factor K_OUT (0.948) above and below alike, the photo's proportions,
        and the envelope is moved down by ENV_DY (41 gp) to meet the photo's
        bottom (owner, 2026-11-08);
  mxl()/mxr(): between the band and the body edge, photo x is scaled so the
        photo's side lands on the envelope's side; parts that stand out beyond
        the side (the record bulge) keep their photo distance from it (x 0.922).
Colours: every colour is turned into a neutral silver grey of the same
luminance (owner: the photo's cream is the lamp's), see silver().
See notes.md for every number.
"""
import os
import sys
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen

S = 0.875
VB_X, VB_Y = -0.3125, -0.25            # the h3900 drawing's canvas
CSS_W, CSS_H = 366, 602            # the h3900 canvas, 17 CSS px taller for the lower body
VB_W, VB_H = CSS_W * 2.1875, CSS_H * 2.1875
GLASS_U = (137.5, 244.75, 525, 700)
GX, GY, GW, GH = 275, 262, 600, 800
TX = GLASS_U[0] - GX * S
TY = GLASS_U[1] - GY * S
CX = 575

# ---- the h3900 envelope (gen_h3900_wide.py, BX and BODY_HALF, y >= 94) ----------
BX = 591
ENV = [(381, 94), (388.5, 100.5), (391.5, 110), (392.3, 125), (390.3, 300),
       (388.6, 400), (387.3, 600), (387, 800), (385, 1000), (383.3, 1100), (381.1, 1200),
       (379.5, 1220), (377, 1236), (371.5, 1246), (362, 1255.5), (350, 1265), (330, 1278.5), (310, 1292.5),
       (270, 1316), (230, 1337), (190, 1353.5), (150, 1369.5), (110, 1379.3), (60, 1386.8),
       (0, 1389.6)]
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
SENSOR_ALS = (748, 172.5, 10.5)       # ambient light sensor (owner, 2026-11-08)

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

FONTS = os.environ.get('IPAQ_FONTS', '/Library/Fonts/')
WORDS = [
    ('iPAQ', 'Roboto_Bold.ttf', 23.4 * K_PAD, 287.5, my(1119.3), 'start', '#3a362f', 66.5 * K_PAD),
    ('Pocket PC', 'Roboto_Regular.ttf', 22.3 * K_PAD, 866, my(1120.8), 'end', '#5a5446', 140.5 * K_PAD),
]


def f(v):
    s = f'{v:.2f}'.rstrip('0').rstrip('.')
    return '0' if s == '-0' else s


def spline(points, closed=True, tension=6.0):
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


def word_path(text, font_file, cap_target, x, y, anchor, width_target):
    font = TTFont(FONTS + font_file)
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    cap = font['OS/2'].sCapHeight
    names = [cmap[ord(c)] for c in text]
    adv = [font['hmtx'][n][0] for n in names]
    bp = BoundsPen(gs)
    pen_x = 0
    for n, a in zip(names, adv):
        gs[n].draw(TransformPen(bp, (1, 0, 0, 1, pen_x, 0)))
        pen_x += a
    xmin, _, xmax, _ = bp.bounds
    ky = cap_target / cap
    kx = width_target / (xmax - xmin)
    ink_w = (xmax - xmin) * kx
    left = {'start': x, 'end': x - ink_w}[anchor] - xmin * kx
    pen = SVGPathPen(gs, ntos=f)
    pen_x = 0
    for n, a in zip(names, adv):
        gs[n].draw(TransformPen(pen, (kx, 0, 0, -ky, left + pen_x * kx, y)))
        pen_x += a
    return pen.getCommands()


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
# photo x moved by SHIFT with the outline; see notes.md
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


def build(debug=False):
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

    if debug:
        red = 'fill="none" stroke="#ff2020" stroke-width="1.5"'
        return (head + group + f'<path d="{body}" {red}/><path d="{cap}" {red}/>'
                f'<path d="{valley}" {red}/><path d="{groove}" {red}/>'
                + ''.join(f'<circle cx="{x}" cy="{y}" r="{BTN_R}" {red}/>' for x, y, _ in BUTTONS)
                + f'<circle cx="{n["cx"]}" cy="{n["cy"]}" r="73" {red}/>'
                f'<circle cx="{POWER["cx"]}" cy="{POWER["cy"]}" r="{POWER["r"]}" {red}/>'
                f'<rect x="{BAND[0]}" y="{BAND[1]}" width="{BAND[2] - BAND[0]}" height="{BAND[3] - BAND[1]}" {red}/>'
                '</g></svg>\n')

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
    leds = ''.join(
        f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="{ry}" fill="{"#3a2420" if i == 1 else "#2a2b2d"}"/>'
        f'<ellipse cx="{x}" cy="{y - 0.6}" rx="{rx - 2.5}" ry="{ry - 2}" fill="{"#a8706a" if i == 1 else "#77787a"}" fill-opacity="0.6" filter="url(#ip-soft)"/>'
        for i, (x, y, rx, ry) in enumerate(LEDS))
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

  <!-- black top piece: polished cap with LEDs, grille, HP plate, ambient light sensor and power button -->
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
    <!-- ambient light sensor: a thin lighter rim round a dark window (owner, 2026-11-08) -->
    <g id="light-sensor" transform="translate(0,{f(my(ay) - ay)})">
      <circle cx="{ax}" cy="{ay}" r="{ar}" fill="#0d0d0e"/>
      <circle cx="{ax}" cy="{ay}" r="{ar - 1.2}" fill="none" stroke="#d8d2c6" stroke-opacity="0.9" stroke-width="2.2"/>
      <circle cx="{ax}" cy="{ay}" r="{ar - 3.8}" fill="#121315"/>
      <path d="M{ax - 4.5},{ay - 3} A6,6 0 0 1 {ax + 1},{ay - 6}" fill="none" stroke="#6c6f73" stroke-opacity="0.5" stroke-width="1"/>
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


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) != 1:
        sys.exit('usage: gen_h5550_final3.py OUT.svg [--debug-outline]')
    with open(args[0], 'w') as fh:
        fh.write(build(debug='--debug-outline' in sys.argv))
