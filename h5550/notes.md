# h5550 frame, final redraw 3: notes

This directory is a copy of `../h5550-final2/` (left untouched) with passes 15-19 added. The first section below describes this round; the rest is the final2 notes, kept for passes 1-14. Where they disagree (mapping, colours, canvas), this section holds.

## Round 3 (passes 15-19): owner decisions 2026-11-08

Output: `h5550-framed-template.svg` (generator `gen_h5550_final3.py`; byte-identical to `work/p19.svg`), SHA-256 `8c6f6500dadbacf5471331df2b8bc4b463670dcaea8d7b2bda755a058228cbc5`; render `h5550-framed-template-render.png`; screenshot test `h5550-test-pr126.svg` / `.png`.

1. Face colour: silver-grey, not the photo's cream (the cast is the lamp's). Every colour in the file is turned into a neutral grey of the same luminance (R -2, B +1.5 for the h3900's slight coolness); greys above luminance 90 are scaled down towards x 0.935 at 200 and above, so the photo's plateau (#f8e7c9, L 233) lands at #d8dadb (L 217), the h3900 face's range (#d2d4d6-#d9dbdc). Kept as they are: the red LED, the glass placeholder, pure white and black. Contrast ratios of ridge, valley, groove and the light direction are the photo's, because luminance is kept proportionally.
   - Top strip (y 235, x 450-700): h5550 L 217, h3900 L 218-224.
   - Bottom band (8-30 gp above the bottom edge, x 300-880, `tools/bottomband.py`): the photo's lit bottom gave L 200-205 against the h3900's 155-166, so a chin band was added (black, 0.24, 56 gp, blurred along the bottom outline): now L 159-167 (the valley legs 106-117), h3900 155-166.
2. Proportions: the photo's. Outside the band the photo is scaled by one factor K_OUT = 0.948 above and below alike (no stretch of the strip above the screen, no 0.839 compression of the pad). K_OUT makes the h5550 10 gp (1 mm) shorter than the h3900 file, as HP's 133 vs 134 mm. The h3900 envelope moves down by ENV_DY = 41.0 gp (35.9 units); its shape, half-widths and length are unchanged. The photo's shoulder corner (y 143) lands at 148.3, on the moved envelope's corner (151-166). Round parts keep the photo's size (K_PAD 1.0): nav r 75.5, buttons r 34.5, dishes 109 x 93, as in the photo; their positions below the band are 5.2 % closer together vertically than in the photo (row spacing 108 -> 102.4 gp; nav centre to bottom 240 -> 228). Above the band the cap outline is scaled by K_OUT; plate, sensor and power button keep their size and move with their centres.
   - Canvas: viewBox `-0.3125 -0.25 800.625 1316.875` (366 x 602 CSS px; 37.2 units taller than the h3900's 1279.6875). At 4x all four edges have alpha 0.
   - Body: cap top 72.0 gp = 78.5 units (antenna top about 33 gp = 44.4 units); bottom 1431.4 gp = 1268.0 units. h3900-wide: top 21.4 gp, bottom 1390.1 gp.
3. Plate: the hp letters are now cut out of the black disc with a mask, so the h's stem and the p's tail break the disc's edge as in the photo (6x crop `work/z16-plate-sensor.png` before, `work/z18-plate.png` after). The final2 drawing clipped them to the disc.
4. Ambient light sensor at 6x (`work/z16-plate-sensor.png`): position and size agree; the photo's ring is thinner and partly lit by the cream reflection, the window not wholly black. Unchanged.

### Width table (glass widths; the envelope moved down 41 gp, so compare h5550 y with h3900 y - 41)

| h5550 y | h5550 | h3900-wide at y - 41 | difference |
|---|---|---|---|
| 662 | 776.9 gp = 1.2948 | 776.2 = 1.2937 | +0.09 % |
| 1000 | 773.1 = 1.2885 | 772.5 = 1.2875 | +0.08 % |
| 1250 | 763.1 = 1.2718 | 763.1 = 1.2718 | 0 |
| 1270 | 758.1 = 1.2635 | 758.1 = 1.2635 | 0 |
| 1291 (corner) | 738.1 = 1.2302 | 736.9 = 1.2282 (y 1250) | +0.16 % |
| 1320 | 660.6 | 660.6 | 0 |

The corner row is the one place over 0.1 %: the outline runs at about 30 degrees there and the 4x render's rows sample 0.29 gp, so 1.2 gp of width is about two rows' difference. The rows 21 gp above and below it agree exactly. Photo: 1.404 at mid-height, 1.367 at y 1250 (not followed, owner's same-body decision).

### Silhouette against h3900-wide (`tools/silcmp.py`, Chrome 2x, 732x1204)

- Against the h3900 moved down by ENV_DY (`work/h3900-shifted.svg`): 1.21 % of the canvas (1.64 % of the union) differs, 9520 px only in the h5550, 1138 only in the h3900 (`work/sil-final-vs-h3900-shifted.png`): the antenna, the record bulge, the right shoulder rim with the stylus head, and in blue the h3900's cap dome above the h5550's flatter top. Sides and bottom coincide, so the envelope difference is the vertical shift alone.
- Against the h3900 as it is (`work/sil-final-vs-h3900.png`): 4.68 % (the shift plus the above).

### Pixel comparison (Chrome 2x white, padded to the same height)

- Against final2: 33.2 % of pixels differ by more than 16, 11.8 % by more than 48.
- Against the previous final (h5550-final): 23.1 % / 11.5 %.
- Against the h3900-wide render: 32.1 % / 19.5 %.

### Passes

15. K_OUT and ENV_DY in place of the stretch and the 0.839 compression; K_PAD 1; canvas 602 CSS px; all colours to neutral silver. Seen (full render): silver face, the strip above the screen back to the photo's size; top strip L 217 against the h3900's 218-224; bottom band L 200-205 against 155-166.
16. Chin band 0.2: bottom band 165-173. Seen in the pad crop: buttons, nav, dishes and groove sit on the mapped photo's positions and sizes. 6x plate: the photo's h stem and p tail break the disc; mine were clipped to it. 6x sensor: as noted above.
17. Chin 0.24 (159-167); letters unclipped. Seen at 6x: the letters' gradient differs from the plate's outside the disc (faint stripes).
18. Letters cut from the disc with a mask instead: clean at 6x.
19. Body spline tension 6, as the h3900 file (widths unchanged; corners checked at 6x, no artefact). Final file. Looked at: full render, screenshot test, cap and pad crops, the shifted silhouette XOR.

## Round 2 (final2) notes

Output: `h5550-framed-template.svg` (generator `gen_h5550_final2.py`; byte-identical to `work/p14.svg`), render `h5550-framed-template-render.png` (Chrome, 2x, white), screenshot test `h5550-test-pr126.svg` / `.png`.
Source: the owner's photograph `frames-ref/owner-photo-20261108.jpg`, rectified as in `../h5550-final/notes.md` (glass on (275,262)-(875,1062) gp, `work/rect.png`). Body envelope: `../h3900-wide/gen_h3900_wide.py` (BX 591, BODY_HALF).
Starting point: `../h5550-final/gen_h5550_final.py` and its notes (copied, then rewritten). `work/gen-pass4-photowidth.py` keeps the generator as it was while the body still had the photograph's width (passes 1-4).
Tools (`tools/`): `outline.py`, `outline2.py` (photo body edges), `colours.py`, `regmean.py`, `rowcmp.py`, `colcmp.py` (photo vs drawing values), `warp_photo.py` (the photo mapped onto the envelope, `work/rect-mapped.png`, for the side-by-sides from pass 5 on), `silcmp.py` (silhouette XOR), `sbs.py`, `zoom.py`, `extent.py`, `embed.py`, `render.sh`, `pass.sh`.

## Instructions over the session (all 2026-11-08, from the coordinator)

1. Body at the photograph's width (no sleeve squeeze); fix power button, nav, face colour, cap, app buttons. Passes 1-4.
2. The top-right part is the POWER BUTTON, not a lens: dark ring round a chrome dome with the power symbol; no concentric rings, no dot highlight.
3. The small ring left of it is the AMBIENT LIGHT SENSOR (owner): keep it as a physical part.
4. The h5550 and the h3900 have the same body (HP: 84 tapering to 77 mm, 133 vs 134 mm long): the outline is the corrected h3900 envelope, same centre line, same top and bottom; draw the photograph's parts inside it. Passes 5-14. This overrides 1.

## Photo measurements added in this round (photo gp)

- Body outer edge, threshold 45 walking in from the background (`tools/outline2.py`; the lit face, threshold 105, where there is no dark wall): left 162.5 / right 1004 at mid-height (centre 583), 171.5 / 992 at y 1250. Widths 1.404 / 1.367 glass widths.
- The left edge includes about 8 gp of the cast shadow's soft edge: the device's black edge line is at 168-180 at y 662 and the background darkens gradually from 148 to 165. On the right the edge is sharp (black at 997-1002, background from 1004).
- The outline is centred at 583 from y 300 to 1250; the cap, the nav button and the groove are centred on 575. So the h5550 photo shows the body 8 photo gp (7.4 drawing gp) right of the glass centre. The h3900 envelope has it 16 gp right (BX 591). I used BX 591 as instructed; the h5550 photo shows the same direction but only about half the amount.
- Bottom: lowest point 1449.5-1450 at x 575-600; half-widths 330 at 1350, 232 at 1400, 116.5 at 1440.
- Face colour, 9x9 px means: plateau #f7e5c7 (top strip), #f9e7c7 (below the glass), #fae7c3 (x 450, y 1100); lit right strip #fefddb-#fffeea (x 940-950); lower face #e3ceae-#e8d4bb; left shadow at y 662 from the edge in: #2a2924, #403930, #595243, #847968, #bfb09c, #edddc1; right: #fcf9dd, #dccbb0, #857a6c, #38332f. The shading follows the edges down: the 150-luminance point moves from 218.6 (y 450) to 229.8 (y 1250) on the left and from 979.5 to 967.6 on the right.
- Antenna (rows): 271-342 at y 25, 245-359 at y 40, 225-365 at y 60, top 18.5-19 at x 305-330.
- Right shoulder rim (columns): top 96 / 101 / 101 / 107 / 121 at x 880 / 900 / 930 / 960 / 980; face top 116 / 119 / 122.5 / 128 / 131. A stylus head stands about 4 gp above the rim at x 932-958.
- Power button (radial profiles from (805,145)): dark dome with reflections r < 24, black ring r 26-38, bright collar r 40-48 (narrowest at the top, centre about (807,147.5)); a light ring at r 16-20 open at the top (the power symbol) and a bright reflection right of the centre at r 8-14.
- Nav button (radial from (575,1210)): mirror disc r < 45 with a large white reflection at 135-225 degrees, r 10-40; bright rim r 44-48; black gap r 50-57; bright ring r 58-60; grey r 62-66; dark line r 66-67; beige collar r 68-76.
- App buttons (radial): black ring r 29-34, domes mid-grey (luminance about 110 at the centre), white highlight on the right and lower right at r 6-26; the printed icons are large (about 35 gp, more than half the dome).
- Dishes: the left ones bright inside on the lower left, dark along the top edge; the right ones shaded inside on the right.
- Groove walls: blades x 502-512 (left) and 640-648 (right), from y 1253 to rounded ends at about 1424.

## The envelope and the mapping (pass 5 on)

- Outline: sides and bottom are `BODY_HALF` of the h3900-wide drawing about BX 591 from y 122 down (stroke 1.7 units, as there). Above that the h5550's own top (cap dome, shoulders, stylus head), the antenna and the record bulge, all from the photo.
- Same top and bottom: bottom 1389.6 gp at the centre (h3900 1389.6). Top of the cap 31.4 gp (h3900 cap top 22): 10 gp, about 1 mm shorter, as HP's 133 vs 134 mm. The antenna stands above that (top at about -13 gp).
- Vertical mapping `my()`: the cap and shoulders move up 31.5 gp as one piece. With that one shift the photo's shoulder corner (y 143) lands at 111.5, on the envelope's corner (110-125), and the cap top lands at 32, the 1-mm-shorter length; I did not force either. The photo's cream strip between the cap (217.6) and the dark band (245) is stretched from 27 to 59 gp. The band and glass stay. Below the band everything is compressed by KB = 0.839 so the photo's bottom (1450.3) lands on 1389.6. Round parts below the band (buttons, dishes, nav) keep their shape and are scaled by 0.92; the valley, groove, sensor bar and microphone are drawn in photo coordinates under `scale(1, 0.839)` about y 1073.6.
- Horizontal mapping `mxl()/mxr()`: identity between the band's outer edges (261-889.5); between the band and the photo's side the photo x is scaled so the side lands on the envelope (left about 0.58-0.62, right about 0.78-0.79); beyond the side (the record bulge) the photo's distance from the side is kept, times 0.922 (envelope width / photo width).
- Antenna: drawn rigid at 0.922, its base placed by the left mapping (x 214 photo -> 234.5).
- Why the mapping is needed: relative to the glass, the photographed body is 8.5 % wider and 5 % longer than the h3900 envelope, and its glass sits higher in the body (198.5 gp above, 388 gp below, against 240 and 328 in the h3900 file). With the glass rect and the envelope both fixed, the strip above the glass has to grow and the pad has to shrink. The alternative, if the owner prefers it: keep the photo's proportions and move the whole envelope 36 gp down (same shape and length, but not the same top and bottom as the h3900 file, and the canvas would have to be about 32 units taller).
- Bottom curve against the photo (photo half-width x 0.922 at the mapped height vs the envelope): +2.7 % at y_d 1255, +4.7 to +6.3 % from 1280 to 1331, +4.5 % at 1347, +3.6 % at 1364, +8.5 % at 1381. More than 2 % everywhere below the corner, so the h3900's bottom (sleeve interface) is used throughout; the photo's bottom is fuller.

## Width table (glass widths, glass = 600 gp)

| y (gp) | owner photo (outer edge) | this drawing (Chrome alpha edge) | h3900-wide drawing (its notes) |
|---|---|---|---|
| 662 (mid-height) | 1.404 | 1.295 (202.5-979.4) | 1.294 |
| 1250 | 1.367 | 1.229 (222.5-960.0) | 1.229 |
| 1000 | 1.385 | 1.287 | 1.286 |
| 150 (bulge) | 1.438 | 1.360 (bulge 167.5) | 1.351 (record housing) |

Photo and drawing do not agree within 1 %: the owner's same-body decision replaced the photo-width instruction. The drawing agrees with the h3900-wide drawing within 0.1 % on the sides, and at y 150 is 0.7 % wider because the h5550's record bulge stands out further than the h3900's record housing.

## Silhouette against the h3900-wide drawing (`tools/silcmp.py`, shadow and glass removed, Chrome 2x, 732x1170)

1.28 % of the canvas (1.68 % of the union) differs: 9682 px only in the h5550, 1280 px only in the h3900 (`work/sil-final-vs-h3900.png`, red = h5550 only, blue = h3900 only). Where: the antenna stub; the record bulge (longer, and 6 gp further out than the h3900's housing); the right shoulder, where the h5550's rim and stylus head sit higher than the h3900's rounded shoulder; and in blue the h3900's cap dome above the h5550's lower, flatter top. Sides and bottom coincide.

## Cap parts: physical or reflection

| Drawn part | Decision | Why |
|---|---|---|
| Cap outline, rim over both shoulders | physical | hard edges in the photo |
| HP plate and hp disc | physical | printed plate with hard edges |
| Grille (four slots, three ridges) | physical | |
| Three LEDs (middle reddish) | physical | the Commons photo shows the red LED |
| Power button: collar, black ring, dome, power symbol | physical | owner; the photo's dome shows the symbol's ring at r 16-20 |
| Ambient light sensor, (748,172.5) photo, r 10.5 | physical | the owner's statement (2026-11-08); drawn as a light rim round a dark window, no highlight |
| Stylus head on the right shoulder | physical | a black bump on the rim with a hard outline |
| Cream area round the power button and right of the plate | reflection | the owner's room in the polished cap; drawn as a soft generic band and a soft patch, not traced |
| Dark shapes inside that cream area | reflection | not drawn |
| White dot in the dome, rings inside the dome | reflection | not drawn (the previous file's concentric rings and dot made it read as a lens) |
| Light line along the cap top | reflection of the top edge | kept faint |

## Passes

Every pass has `passN.png` (2x white), `work/pN-big.png` (6x transparent) and `sbs/pN-*.png` (photo left, drawing right, same gp region): silhouette, cap, antenna-leds, power, plate, band-top, band-bottom, pad, groove, bottom, buttons-left, buttons-right, left-side, right-side. Passes 1-4 compare against the rectified photo; from pass 5 the photo is mapped onto the envelope (`work/rect-mapped.png`) with the generator's own mapping, so the two halves line up. The mapped photo's pad parts are squashed vertically by 0.839 while the drawing's round parts stay round.

1. Photo width, all positions from the photo, outline shifted 8 gp left to centre it. Seen: drawing face looks more yellow at small size, but region means equal the photo's (top strip #f7e5c7 / #f8e7c8); the difference is the photo's texture. The left shading was in the wrong place lower down (the photo's dark core moves from 172 to 186 between y 662 and 1150).
2. Shading skewed along the edges (0.015). Seen: power button reads as a power button; collar too thick and too evenly white; dome too large; nav disc too dark and its chrome rim at the wrong radius; app buttons black with a white bar; valley too faint (photo 0x68 vs 0xa3 at (410,1300)).
3. Rim lower edge re-measured, stylus head added, collar and dome resized, nav rebuilt from the radial profile, domes lighter, valley darker on the left than the right. Seen: icons too small and faint; highlight at the rim instead of inside; dishes lit the wrong way; antenna cool grey against the photo's warm dark grey.
4. Icons 1.55x and stronger, highlights moved in, dish shading as the photo, antenna warm, LEDs lighter, cap base warmer, reflection brighter.
5. Envelope from the h3900-wide drawing, mappings `my()`, `mxl()`, `mxr()`, canvas of the h3900 file. Seen: a dark rim tail at the top-right corner outside the body; the left rim ran into the bulge; collar still thick.
6. Cap clipped to the body; left rim shortened to the face corner; collar r 47.5; nav black gap lighter. Seen (row profiles): right shading too far out at the top; bulge uniform grey where the photo has a black band along its outer edge; cap left part lighter than the photo (25-40 vs 4-20).
7. Right skew 0.005; bulge wall and black band; left sheen removed; reflection reshaped; band lip fainter. Seen: band 8 gp too far in at y 300.
8. Band offset; grille slots thinner, ridges lighter. Seen: the band read as a separate stripe.
9. Band along the edge, rounded and blurred; bottom edge shading lighter. Row check y 160-380: photo and drawing within 20 except the black, which was too light.
10. Band darker and wider. Seen at 6x: a spike at the top-right corner of the outline (spline overshoot over the long segment from y 111.5 to 300).
11. Envelope samples at y 122-250 added: spike gone.
12. viewBox written exactly as the h3900's (`-0.3125 -0.25 800.625 1279.6875`; before it was rounded to 2 decimals). Screenshot test made: the picture fills the glass inside the dark band, no gap at the corners (`work/z12-glass.png`).
13. Groove walls: blades with rounded ends at photo y 1424 instead of points at the bottom edge, grey not black.
14. Power symbol r 15.5 and dome r 26.5 (photo ring r 16-20). Final file.

## Screenshot test

`h5550-test-pr126.png`: `pr126-matched-after.png` (240x320) on `<rect id="screen">`, pixelated. Looked at in full and at 6x at two corners: the picture sits inside the dark band with the glass edge line under its border, no gap.

## Pixel comparison (same Chrome command, 2x, white; canvases padded to the same height)

- Against the previous final (`../h5550-final/h5550-framed-template-render.png`, 732x1240): 37.8 % of pixels differ by more than 16 in some channel, 18.7 % by more than 48.
- Against the h3900-wide render (732x1170): 37.1 % by more than 16, 25.7 % by more than 48 (face colour, cap, pad; the silhouettes differ by 1.28 %).

## Canvas

viewBox `-0.3125 -0.25 800.625 1279.6875`, 366 x 585 CSS px, the h3900-wide file's. At 4x the top row has alpha at most 2/255 (the antenna's shadow), the other edges 0.
