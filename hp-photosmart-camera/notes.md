# HP Photosmart Mobile Camera

The 1.3 megapixel camera that plugs into the SD slot of the iPAQ h2200 (and other SD-slot iPAQs): a champagne-silver body with the badge and the name, a head with a protruding lens barrel, and a black plug in the shape of an SD card ("1.3 MP", "4x digital zoom", the SD mark, a cut corner at the lower left, "PUSH" above it).

## Files

| File | What |
|---|---|
| `hp-photosmart-camera.svg` | front view, lens facing the viewer (the position for taking pictures of yourself) |
| `hp-photosmart-camera-away.svg` | the head turned half way round: the plain back of the head shows (the position for regular pictures) |
| `hp-photosmart-camera-swivel.svg` | the head turning between the two, SMIL, 10 s loop (hold front, 4 s turn, hold away, 3 s back); no script |
| `hp-photosmart-camera-above.svg` | seen from above and in front |
| `on-h2200.svg`, `on-h2200-swivel.svg` | the camera in the h2200 frame, the plug disappearing into the slot at the top; the glass rectangle `id="screen"` has the coordinates of `../h2200/ipaq-h2200.svg` (x=137.5 y=168, 525 x 700), because only the viewBox grows upwards |
| `gen-camera.js`, `compose-on-h2200.py` | the generators; `node gen-camera.js .` writes the four camera drawings, `python3 compose-on-h2200.py` the two composites. The output is byte for byte the committed SVGs |
| `preview.png`, `preview-on-h2200.png` | renders of the front view and the composite |

## How the head turns

The head is one assembly: the head block, the lens barrel (a real cylinder, a ring with a glass seen from the front), the ring face and the two focus marks. It rotates about the horizontal axis that runs from the body into the head, perpendicular to the seam between them. That is the axis the photographs show: with the lens pointing up the barrel stands up, and half a turn later the plain back of the head faces the viewer. The body and the plug stay still. The generator projects a small 3D model (orthographic, a slight view from above) and puts shading on the faces by their angle.

## Measurements

Taken from a straight product photograph and checked against photographs of the camera on an iPAQ h2200. With the body width W: the head is 0.85 W wide and 0.81 of the body height, its top slightly above the body; the foot under the head reaches 0.18 W further right; the lens outer diameter is 0.62 W; the plug is 0.8 W wide and runs from 0.3 W to 1.12 W, with the step on its left edge and the 45 degree cut corner at the lower left. In the composite the plug is 24 mm (an SD card) against the 71 mm width of the iPAQ.

Every text sits inside its shape: a script measured the on-screen box of each text in Chrome and required at least 3 px of margin in every frame of the animation.

## What differs from the real thing

The surfaces are flatter and the edges sharper than the brushed metal. The body text is a little heavier than the thin type on the real camera. The hp logo and the SD mark are simplified drawings, not the artwork.

## Credits

The photographs the geometry was measured from are the author's own and are not distributed; nothing was traced or embedded. HP, iPAQ, Photosmart, Pocket PC and SD are trademarks of their owners and appear only to identify the devices.
