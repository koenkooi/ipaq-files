#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Koen Kooi
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Puts the camera drawings onto the h2200 frame: the camera is drawn first and
# the frame over it, so the plug disappears into the slot at the top. The
# canvas grows upwards by changing the viewBox only, so the glass rectangle
# (id="screen") keeps its coordinates from ../h2200/ipaq-h2200.svg.
#
# Usage: python3 compose-on-h2200.py [output directory]
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1] if len(sys.argv) > 1 else HERE
SCALE = 1.08   # the 244 unit wide plug is a 24 mm SD card, the iPAQ is 71 mm wide
PLUG_X = 370   # x of the plug centre in the frame
SEAT_Y = 26    # y in the frame where the camera's y=340 (just under the body) sits
VARIANTS = (
    ("hp-photosmart-camera.svg", "on-h2200.svg", "the lens facing the viewer"),
    ("hp-photosmart-camera-swivel.svg", "on-h2200-swivel.svg",
     "the lens facing the viewer; animated, the head turns to show its back (10 s loop)"),
)

def inside(text):
    return re.search(r'<svg[^>]*>(.*)</svg>', text, re.S).group(1)

frame = inside(open(os.path.join(HERE, "..", "h2200", "ipaq-h2200.svg")).read())
frame = re.sub(r'<!--.*?-->', '', frame, count=1, flags=re.S)
tx = PLUG_X - 214 * SCALE
ty = SEAT_Y - 340 * SCALE
extra = -(ty - 30 * SCALE) + 20     # room above the frame for the camera
for src, name, what in VARIANTS:
    cam = inside(open(os.path.join(HERE, src)).read())
    cam = re.sub(r'<title[^>]*>.*?</title>|<desc[^>]*>.*?</desc>|<!--.*?-->', '', cam, flags=re.S)
    H = 1180 + extra
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="800" height="{H:.0f}" viewBox="0 {-extra:.2f} 800 {H:.2f}" role="img" aria-labelledby="t d">
<title id="t">HP iPAQ h2200 with the HP Photosmart Mobile Camera</title>
<desc id="d">An iPAQ h2200 seen from the front with the HP Photosmart Mobile Camera plugged into its SD slot at the top, {what}. The glass rectangle id="screen" is at x=137.5 y=168, 525 x 700.</desc>
<!--
  SPDX-FileCopyrightText: 2026 Koen Kooi
  SPDX-License-Identifier: CC-BY-SA-4.0

  Provenance: an original vector drawing, composed by compose-on-h2200.py from
  ../h2200/ipaq-h2200.svg and {src}; no photograph is embedded. "HP", "iPAQ",
  "Pocket PC", "Photosmart" and "SD" are trademarks of their owners and appear
  only to identify the devices.
-->
<g id="camera" transform="translate({tx:.2f} {ty:.2f}) scale({SCALE})">{cam}</g>
<g id="ipaq">{frame}</g>
</svg>
'''
    open(os.path.join(OUT, name), "w").write(svg)
    print(name, len(svg))
