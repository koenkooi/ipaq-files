# h3900 frame, body width from the owner's photographs: notes

Output: `h3900-framed-template.svg` (generator `gen_h3900_wide.py`, a copy of `h3900-frame/gen_h3900_v2.py` with the body changed), render `h3900-framed-template-render.png` (Chrome, 2x, white).
`gen_h3900_v2.py` is the generator of the old template: its output is byte-identical to `h3900-frame/out/h3900-framed-template.svg` (sha256 6cc20e5e...b288). `gen_h3900.py` gives a different file.
Tools in `tools/`: `rectify.py`, `measure.py`, `contour.py`, `tape_profile.py`, `overlay.py`, `overlay_lib.py`, `grid.py`, `render.sh`, `pass.sh`, `sbs.py`, `widths.py`.

## Photographs looked at

`h3900-frame/photos/`: `front-owner.jpg` (straight front, 1206x1491; used), `front-rect.png` (the earlier rectification of the same photo; not used), `tape-landscape.jpg` (device on its side under a tape measure; used as the cross-check), `closeup-top-left.jpg` and `end-top-oblique.jpg` (oblique; not measured).

## Rectification

- Edges of the screen opening (bright bevel to the dark border) fitted in `front-owner.jpg` on the largest gradient in a 28 px window, 87 rows / 63 columns, outlier rejection. Residual sd: left 0.17, right 0.17, top 0.72, bottom 0.30 photo px.
- Corners TL (266.8, 273.2), TR (863.1, 258.9), BR (886.8, 1047.9), BL (290.0, 1067.0). Top width 596.3, bottom 596.7, left height 793.8, right 789.0; w/h 0.7538 against 606/806 = 0.7519.
- The fitted edge is the outer edge of the generator's 3 px dark border, so it maps to glass +-3: (272,259)-(878,1065) gp. Output `work/rect.png`, 2 px per gp.

## What the photographs show

Width at the mid-level luminance crossing, in glass widths (600 gp):

| y (gp) | front photo L..R | width | tape photo (body/opening x 606/600) |
|---|---|---|---|
| 150 (record housing) | 171.8..982.8 | 1.352 | - |
| 300 | 199.3..981.6 | 1.304 | 1.316 (upper third of the glass) |
| 662 | 202.1..977.5 | 1.292 | 1.302-1.308 (middle) |
| 1000 | 206.2..978.0 | 1.286 | 1.293-1.295 (lower end) |
| 1200 | 210.0..973.9 | 1.273 | - |
| 1250 (corner) | 223.3..957.9 | 1.224 | - |

The outer edge (first rise 25 above the background) adds 1-2 % (1.303 at y 662); on the lower right that number is spoiled by a lighter patch of desk.
The two photographs agree within 1 %. Neither shows 1.34-1.46. On the tape the opening is 351-354 px and the body 453-457 px at about 6.0 px/mm: opening about 58.5-59 mm, body about 76-77 mm. The 1.34 figure divides 77 mm by the 57.6 mm active area; the drawing maps the visible opening (about 59 mm) to the glass rect, and 77 / 59 = 1.30, which is what both photos show. Both photos see the sides from slightly above, so a side's widest point a few mm below the face can read 1-3 % narrow; I did not correct for that because I cannot measure the camera distance.

The body is not centred on the glass: margins 73 gp left, 102 gp right at y 662 in the front photo; 41-43 px left, 60-63 px right in the tape photo (ratio 0.66-0.71 in both). The bottom curve is symmetric about x 590 (heights at +-70, +-110, +-190, +-310, +-350 agree within 1-6 gp). In the tape photo the camera position would, if anything, hide the right side wall, so the larger right margin is not a side wall seen at an angle. The h5550 photo shows the same direction (113.5 / 129 gp).
The cap, nav ring (outer edges 404/739, centre 572), the four button rings (fit within 0-4.5 gp of v2: calendar (319.5,1227.5), contacts (383.5,1184.5), mail (763.5,1177.5), task (829,1222.5)) and the wordmarks sit where v2 has them, on the screen centre. So the old drawing was only 1.5 % narrow, but 16 gp off-centre: its left side 10-13 gp too far out, its right side 17-24 gp too far in.

## Changes against v2

- `BX = 591`: body centre line; `BODY_HALF` re-measured about it (left and right averaged, less 1.2 gp for the outline stroke). Top edge 72.5 (dx 245) to 94 (dx 381); sides 392.3 (y 125) tapering to 379.5 (y 1220); corner 1236-1265; bottom 1389.6 at the centre (v2 1393), flatter: 1379.3 at dx 110, 1353.5 at dx 190.
- `LEFT_TOP`: the left shoulder 3-5 gp lower than the right, as in the photo, so it runs into the record housing's chamfer without a step.
- `RECORD_PTS`: record housing re-measured: straight chamfer (214,96.5) to (174.5,128), outer edge 173.5 from y 128 to 190 (v2 165), back into the side by y 290.
- Face gradient, side curl lines, shoulder highlight and chin strokes follow BX and the new half-widths.
- Kept (the photo shows no measurable difference): glass rect, bevel and dark border (the "bezel"; it belongs to the glass, not the body), cap, COMPAQ/iPAQ/Pocket PC, pad, button positions and spread, power button, LED.
- Header: SPDX and provenance kept; one sentence added on the body width correction.
- viewBox unchanged (`-0.3125 -0.25 800.625 1279.6875`): the body now ends at 757.3 units on the right and 48.7 on the left; the shadow decays to alpha 0 before both canvas edges (checked on the 4x render). The glass rect has not moved.

## Passes

Each pass: `passN.png` (2x white), `work/pN-big.png` (4x transparent), `sbs/pN-*.png` (photo left, drawing right, same gp region): silhouette, cap, band, pad, bottom, left-side, right-side, left-low, right-low, record. `sbs/old-*.png` are the same crops of v2.

1. First build with BX and the new BODY_HALF. Seen: sides and bottom on the photo edges in `work/ov-p1.png`; bottom flatter and rounder like the photo; the face's top-left corner stands out above the record housing as a notch (photo: the shoulder runs straight into the housing's chamfer).
2. LEFT_TOP added. Seen: notch gone; housing top still rounder than the photo's straight chamfer; right-low corner tighter than the photo.
3. Chamfer points and softer bottom corners. Seen: cap identical to v2 and matching the photo; pad and buttons unchanged; bottom centre within about 3 gp.
4. More chamfer points. Measured the render with the photo's method (`tools/widths.py`): right side 2-3 gp wide of the photo because the outline stroke adds 0.86 gp a side.
5. Side half-widths less 1.2 gp. Widths now within 1-3 gp of the photo at every row checked. This is the final file. The housing's top corner is still slightly rounder than the photo (about 3 gp at the corner).

## Width table (glass widths; drawing = Chrome render alpha edge, photo = mid-level crossing)

| y | photo | old (v2) | new |
|---|---|---|---|
| 150 (top, with record housing) | 1.352 | 1.329 | 1.351 |
| 300 | 1.304 | 1.285 | 1.304 |
| 662 (mid-height) | 1.292 (outer 1.303) | 1.277 | 1.294 |
| 1000 | 1.286 | 1.267 | 1.286 |
| 1200 | 1.273 | 1.250 | 1.274 |
| 1250 | 1.224 | 1.229 | 1.229 |

## Pixel difference against v2 (same Chrome command, 2x, white, 732x1170)

8.45 % of pixels differ by more than 16 in some channel, 3.39 % by more than 48. `diff-old-new.png` (red > 16, dark red > 48) and `old-new-diff-sbs.png` (old | new | mask): all changes are along the sides, the record housing, the shoulder line and the bottom outline with its chin strokes; inside the glass columns only the bottom curve (y 1281-1396) and the shoulder line (y 71-90) changed.
