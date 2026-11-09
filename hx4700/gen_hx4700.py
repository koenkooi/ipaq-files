#!/usr/bin/env python3
"""Generate the HP iPAQ hx4700 framed-screenshot template SVG.

usage: <venv>/bin/python gen_hx4700.py OUT.svg [--debug-outline]

Geometry is measured on ref/rect.png: the reference photograph (HP iPAQ
hx4700 - Front.jpg, Beamish4, CC BY-SA 4.0), turned upright and rectified with
tools/rectify.py so that the lit-glass area is an upright 3:4 rectangle at
x 1100..2876, y 1650..4018 ("photo px"). Everything below is in those pixels
and is drawn inside a group that maps them to SVG units at 525/1776 units per
photo px, so the glass lands on <rect id="screen"> x=137.5 y=244.75 525x700.

The glass sits about 20 px right of the centre of the face plane in the photo
(parallax: the glass is recessed and the camera stood to the right). A front
view centres the face on the glass, so features on the face plane are measured
relative to the face centre (photo x 1966) and drawn relative to the glass
centre (CX). Their x values below are offsets from that centre ("rel").

--debug-outline writes only key outlines as red strokes, for overlaying on the
rectified photo.
"""
import math
import random
import os
import sys
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen

# ---- canvas and mapping ----------------------------------------------------
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

FONTS = os.environ.get('IPAQ_FONTS', '/Library/Fonts/')
IPAQ = dict(text='iPAQ', font='OpenSans_Bold.ttf', x0=-872, x1=-716, base=4262, cap=54)
# -----------------------------------------------------------------------------


def f(v):
    s = f'{v:.2f}'.rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def mirror(half, cx=CX):
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


def rounded(pts, radii):
    """Closed polygon with each corner rounded by a quadratic of the given cut-back."""
    n = len(pts)
    segs = []
    for i in range(n):
        p, q = pts[i], pts[(i + 1) % n]
        segs.append((p, q))
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


def cap_h(y):
    return CAP_H0 + CAP_SLOPE * (1300 - y)


def bp_h(y):
    return BP_H0 + BP_SLOPE * (y - 4220)


def word_path(text, font_file, x0, x1, base, cap):
    font = TTFont(FONTS + font_file)
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    capu = font['OS/2'].sCapHeight
    names = [cmap[ord(c)] for c in text]
    adv = [font['hmtx'][n][0] for n in names]
    bp = BoundsPen(gs)
    pen_x = 0
    for n, a in zip(names, adv):
        gs[n].draw(TransformPen(bp, (1, 0, 0, 1, pen_x, 0)))
        pen_x += a
    xmin, _, xmax, _ = bp.bounds
    ky = cap / capu
    kx = (x1 - x0) / (xmax - xmin)
    left = x0 - xmin * kx
    pen = SVGPathPen(gs, ntos=f)
    pen_x = 0
    for n, a in zip(names, adv):
        gs[n].draw(TransformPen(pen, (kx, 0, 0, -ky, left + pen_x * kx, base)))
        pen_x += a
    return pen.getCommands()


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


def build(debug=False):
    body = spline(mirror(BODY_HALF))
    face = spline(mirror(FACE_HALF))
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
    group = f'<g transform="matrix({f(S * 1e5 / 1e5)} 0 0 {f(S)} {f(TX)} {f(TY)})">'
    group = f'<g transform="matrix({S:.6f} 0 0 {S:.6f} {TX:.4f} {TY:.4f})">'

    if debug:
        red = 'fill="none" stroke="#ff2020" stroke-width="4"'
        return (head + group + f'<path d="{body}" {red}/><path d="{face}" {red}/>'
                f'<path d="{cap}" {red}/><path d="{bpanel}" {red}/><path d="{pad}" {red}/>'
                f'<rect x="{o0[0]}" y="{o0[1]}" width="{o0[2]-o0[0]}" height="{o0[3]-o0[1]}" {red}/>'
                f'<rect x="{o1[0]}" y="{o1[1]}" width="{o1[2]-o1[0]}" height="{o1[3]-o1[1]}" {red}/>'
                '</g></svg>\n')

    ipaq = word_path(IPAQ['text'], IPAQ['font'], CX + IPAQ['x0'], CX + IPAQ['x1'], IPAQ['base'], IPAQ['cap'])

    leds = ''.join(
        f'<g transform="translate({f(CX + x)},{y}) rotate({LED_ANG})">'
        f'<rect x="{f(-LED_W/2 - 3)}" y="{f(-LED_L/2 - 3)}" width="{LED_W + 6}" height="{LED_L + 6}" rx="5" fill="#050506"/>'
        f'<rect x="{f(-LED_W/2)}" y="{f(-LED_L/2)}" width="{LED_W}" height="{LED_L}" rx="2" fill="url(#hx-led)"/>'
        f'<circle cx="{f(LED_W/2 - 3)}" cy="{f(LED_L/2 - 2)}" r="4" fill="#fff" fill-opacity="0.8"/></g>'
        for x, y in LEDS)
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
    # hp letters on a unit grid (disc radius 1), slanted strokes
    sl = 0.32   # horizontal shift per unit of height (italic slant)
    def bar(xc, y0, y1, w=0.21):
        # parallelogram bar from y0 to y1 (unit coords), centred on xc at y=0
        return (f'M{f((xc - w/2 - sl*y0) * R)},{f(y0 * R)} L{f((xc + w/2 - sl*y0) * R)},{f(y0 * R)} '
                f'L{f((xc + w/2 - sl*y1) * R)},{f(y1 * R)} L{f((xc - w/2 - sl*y1) * R)},{f(y1 * R)} Z')
    hp_letters = (bar(-0.40, -1.02, 0.42) + bar(-0.02, -0.20, 0.42) + bar(0.20, -0.20, 1.12) + bar(0.58, -0.20, 0.42)
                  + f' M{f((-0.40 + 0.085 - sl*-0.1)*R)},{f(-0.1*R)} Q{f((-0.05 - sl*-0.3)*R)},{f(-0.32*R)} {f((-0.02 + 0.085 - sl*-0.16)*R)},{f(-0.16*R)}'
                  f' L{f((-0.02 - 0.085 - sl*-0.03)*R)},{f(-0.03*R)} Q{f((-0.14 - sl*-0.12)*R)},{f(-0.14*R)} {f((-0.40 + 0.085 - sl*0.06)*R)},{f(0.06*R)} Z'
                  + f' M{f((0.20 + 0.085 - sl*-0.1)*R)},{f(-0.1*R)} Q{f((0.55 - sl*-0.3)*R)},{f(-0.32*R)} {f((0.58 + 0.085 - sl*-0.16)*R)},{f(-0.16*R)}'
                  f' L{f((0.58 - 0.085 - sl*-0.03)*R)},{f(-0.03*R)} Q{f((0.42 - sl*-0.12)*R)},{f(-0.14*R)} {f((0.20 + 0.085 - sl*0.06)*R)},{f(0.06*R)} Z'
                  + f' M{f((0.20 + 0.085 - sl*0.36)*R)},{f(0.36*R)} Q{f((0.45 - sl*0.5)*R)},{f(0.48*R)} {f((0.58 - 0.085 - sl*0.3)*R)},{f(0.3*R)}'
                  f' L{f((0.58 + 0.085 - sl*0.36)*R)},{f(0.36*R)} Q{f((0.5 - sl*0.62)*R)},{f(0.62*R)} {f((0.20 + 0.085 - sl*0.5)*R)},{f(0.5*R)} Z')
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
    <stop offset="0" stop-color="#8a8b8d"/><stop offset="0.45" stop-color="#b9babc"/><stop offset="1" stop-color="#76777a"/>
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


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) != 1:
        sys.exit('usage: gen_hx4700.py OUT.svg [--debug-outline]')
    with open(args[0], 'w') as fh:
        fh.write(build(debug='--debug-outline' in sys.argv))
    print('wrote', args[0])
