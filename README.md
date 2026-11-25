# ipaq-files

Vector front views of HP and Compaq iPAQ and Sharp Zaurus handhelds, used as frames around screenshots in the documentation of picowl, picoUI, picoplayer and the other pico* projects. Each SVG has a rectangle `id="screen"` where the screenshot goes.

| Device | Drawing | Preview | Glass in the SVG | Screen |
|---|---|---|---|---|
| iPAQ h2200 | [h2200/ipaq-h2200.svg](h2200/ipaq-h2200.svg) | ![h2200](h2200/preview.png) | x=137.5 y=168 525 x 700 | 240x320 |
| iPAQ h2200 with thumb keyboard | [h2200/ipaq-h2200-keyboard.svg](h2200/ipaq-h2200-keyboard.svg) | <img src="h2200/preview-keyboard.png" width="183" alt="h2200 with keyboard"> | x=137.5 y=168 525 x 700 | 240x320 |
| iPAQ h3900 | [h3900/h3900-framed-template.svg](h3900/h3900-framed-template.svg) | ![h3900](h3900/preview.png) | x=137.5 y=244.75 525 x 700 | 240x320 |
| iPAQ h5550 | [h5550/h5550-framed-template.svg](h5550/h5550-framed-template.svg) | ![h5550](h5550/preview.png) | x=137.5 y=244.75 525 x 700 | 240x320 |
| iPAQ hx4700 | [hx4700/hx4700-framed-template.svg](hx4700/hx4700-framed-template.svg) | ![hx4700](hx4700/preview.png) | x=137.5 y=244.75 525 x 700 | 480x640 |
| Zaurus SL-5500 (Collie) | [sl-5500/sl-5500-framed-template.svg](sl-5500/sl-5500-framed-template.svg) | <img src="sl-5500/preview.png" width="183" alt="Collie closed"> <img src="sl-5500/preview-open.png" width="183" alt="Collie open"> | x=137.5 y=168 525 x 700 | 240x320 |
| Zaurus SL-5600 (Poodle) | [sl-5600/sl-5600-framed-template.svg](sl-5600/sl-5600-framed-template.svg) | <img src="sl-5600/preview.png" width="183" alt="SL-5600 closed"> <img src="sl-5600/preview-open.png" width="183" alt="SL-5600 open"> | x=137.5 y=168 525 x 700 | 240x320 |
| Zaurus SL-6000 (Tosa) | [sl-6000/sl-6000-framed-template.svg](sl-6000/sl-6000-framed-template.svg) | <img src="sl-6000/preview.png" width="183" alt="SL-6000 closed"> <img src="sl-6000/preview-open.png" width="183" alt="SL-6000 open"> | x=137.5 y=168 525 x 700 | 480x640 |
| Zaurus SL-C700, laptop | [sl-c700/sl-c700-laptop.svg](sl-c700/sl-c700-laptop.svg) | ![C700 laptop](sl-c700/preview.png) | x=255 y=92 700 x 525 | 640x480 |
| Zaurus SL-C700, folded | [sl-c700/sl-c700-pda.svg](sl-c700/sl-c700-pda.svg) | ![C700 folded](sl-c700/preview-pda.png) | x=165 y=195 525 x 700 | 480x640 |

The h3900 and h5550 share a body outline (same width, same expansion sleeves). The 240x320 screens use 2.1875 units per pixel; the VGA screens use 1.09375.

## Using a frame

Put the screenshot in the glass rectangle, for example as an `<image>` element with the rectangle's position and size, and draw it before the bezel highlights if you need the reflection on top. The SVGs contain no external references.

For the inline Collie SVG, replace the rectangle with an image, keeping its ID and geometry. Use `#poodle` instead of `#collie` for the SL-5600. Here `screenshotDataUrl` is a PNG data URL supplied by the application:

```js
const glass = document.querySelector("#collie #screen");
const image = document.createElementNS("http://www.w3.org/2000/svg", "image");
for (const name of ["id", "x", "y", "width", "height"]) image.setAttribute(name, glass.getAttribute(name));
image.setAttribute("href", screenshotDataUrl);
glass.replaceWith(image);
```

Browsers can block linked images inside an SVG used as an `<img>`; use a data URL there. Set `image.style.imageRendering = "pixelated"` for sharp low-resolution captures. All three sliding Zaurus frames use the same glass coordinates as the h2200 frame in picoDoom; the SL-6000 uses a 480x640 capture.

## Sliding keyboards and controls

The SL-5500, SL-5600 and SL-6000 SVGs default to the closed position. Append `#open` to the SVG path for the open view in an `<img>`, or load the SVG in a browser or `<object>` and click or keyboard-activate the slider strip to toggle it. An `<img>` is not interactive.

For an interactive `<object>`, reserve the open height, for example `<object type="image/svg+xml" data="sl-5500/sl-5500-framed-template.svg" width="320" height="668"></object>`. At the same width, use height `700` for the SL-5600 or `688` for the SL-6000. The closed view leaves blank space below the device; the screen stays in the same position in both views. A same-origin application can attach handlers through `object.contentDocument`.

For an inline SVG without a `#open` page fragment, handle the strip links without navigating the page. Select `#poodle` or `#tosa` instead of `#collie` for the other sliders:

```js
const frame = document.querySelector("#collie");
for (const open of [true, false]) {
  frame.querySelector(open ? "#open-keyboard" : "#close-keyboard").addEventListener("click", event => {
    event.preventDefault();
    frame.setAttribute("data-keyboard", open ? "open" : "closed");
    frame.setAttribute("viewBox", frame.querySelector(open ? "#open" : "#closed").getAttribute("viewBox"));
  });
}
```

Controls have IDs such as `button-up`, `button-select`, `button-home`, `key-q` and `key-space`; they are hit targets, not built-in simulation logic.

Set the `fill` of `#led-mail` or `#led-charge` to change its colour, for example `frame.querySelector("#led-mail").setAttribute("fill", "#36d966")`. Use `#252626` for off; the SL-5500 and SL-5600 charge light defaults to `#ffb823`. The SL-6000 also has `#led-wlan` and `#led-bluetooth`, with all four off initially. The lens shading stays in place.

Some static SVG renderers ignore fragment views or CSS transforms. To export the open view with those tools, set `viewBox="0 40 800 1670"` on a Collie copy and `transform="translate(0 290)"` on its `<g id="slider">`. For the SL-5600, use `viewBox="0 40 800 1750"` and `transform="translate(0 370)"`; for the SL-6000, use `viewBox="0 40 800 1720"` and `transform="translate(0 340)"`.

The SL-5500 US QWERTY layout follows Sharp's [Start-up Guide](https://archive.org/download/ZaurusSL5500Software/SL5500SUG_Final.pdf); the SL-5600 layout follows photographs. Outlines and slider travel are estimated from screen-rectified photographs, not CAD: the photos imply slightly different body widths, and the brushed finish and ball reflections are simplified.

The black SL-6000 follows Sharp's [product photographs and specifications](https://jp.sharp/products/sl6000/) and [operation manual](https://www.manualslib.com/manual/807955/Sharp-Sl-6000l.html?page=27). Its protective flip cover is omitted. The small left dot-marked button is a second OK control, not a printed Ctrl key. Wireless indicators vary between N/L/W models; the drawing exposes both wireless lights for simulation.

The optional h2200 keyboard follows the owner's attached and detached photographs: 37 domed keys in bowed rows, orange alternate legends and blue casing legends. It covers the lower controls, as the real accessory does, without moving or covering the screen. `addon-keyboard` contains independent `key-*` targets. The original h2200 SVG remains unchanged.

## SL-C700 views and controls

The laptop and folded frames are separate SVGs. Use a landscape 640x480 capture for the laptop, or a portrait 480x640 capture for the folded view. Replace `#screen` as above, selecting `#c700-laptop` or `#c700-pda` instead of `#collie`.

The laptop has `key-*` and `button-*` hit targets; both views have `touch-home`, `touch-mail`, `touch-address`, `touch-calendar` and `touch-clock` for the five touchscreen shortcuts. Set the fill of `#led-mail` or `#led-charge` to recolour the indicators; both default to `#252626` (off). These targets have no built-in simulation logic.

Both views use the same shortcut glyphs, size and ink colour. Their diagonal printing turns 90 degrees with the lid rather than being redrawn upright for each screen orientation.

The key faces and lower controls share one perspective plane; their legends use local affine approximations. The screen stays rectangular for straightforward screenshot placement. Shell proportions, reflections and small printed markings are approximations based on photographs.

## Regenerating

The h3900, h5550 and hx4700 generators write the SVG to the file named on the command line:

```
IPAQ_FONTS=/usr/share/fonts/truetype/ python3 h5550/gen_h5550_final3.py out.svg
```

They need Python 3 with fontTools and these fonts in `IPAQ_FONTS` (default `/Library/Fonts/`): Mukta_Regular, OpenSans_Bold, OpenSans_BoldItalic, Roboto_Bold, Roboto_Regular. The printed marks (iPAQ, Pocket PC, COMPAQ) are converted to glyph outlines in the SVG, so the fonts are only needed to regenerate. The output is byte for byte the committed SVG when the same font files are used. The generators measure positions on reference photographs (rectified so the glass is an upright 3:4 rectangle); the photographs are not part of this repository, and nothing from them is copied into the drawings.

The h2200 drawing was written by hand and has no generator.

### Measurement conventions

These are measured front-view approximations, not CAD or traced photographs. References are rectified against the visible screen opening; no photograph is distributed or embedded.

- **h3900:** the owner's front and tape photographs agree within about 1% on a body/opening width near 1.30 (roughly 76–77 mm over a 58.5–59 mm opening), rather than dividing by the smaller active display area. The body is offset right of the screen: centre 591 versus 575 in the 600-pixel-wide rectified-glass coordinates. The left shoulder and record housing are measured separately; the bottom centre is at 1389.6. Mapping uses 0.875 SVG units per photo pixel.
- **h5550:** the same expansion-sleeve body envelope is used, despite the photograph suggesting a wider body. The envelope moves down 41 photo pixels; outside the screen band, vertical spacing scales by about 0.948, while round controls retain their size. The body is approximately 1 mm shorter than the h3900 (published 133 versus 134 mm). The photograph's warm lamp cast is neutralised to silver-grey; the power button is a chrome dome with a power symbol, and the smaller adjacent window is the ambient-light sensor. The hp letters cut through the badge disc.
- **hx4700:** the rectified glass is 1776×2368 photo pixels, mapped at 525/1776 SVG units per pixel. Face-plane features are recentered by 22 photo pixels to remove camera parallax. The body ratio is about 1.71 versus the published 131×77 mm ratio of 1.70. The asymmetric cap, chamfered lower corners and grain are intentional; unreadable small labels are represented by faint marks rather than invented words.

## Credits

| What | Source | Licence |
|---|---|---|
| hx4700 reference photograph (geometry measured, nothing traced) | "HP iPAQ hx4700 - Front.jpg" by Beamish4, Wikimedia Commons | CC BY-SA 4.0 |
| Collie reference photograph (geometry measured, nothing traced) | ["Sharp Zaurus SL-5500G.jpg"](https://commons.wikimedia.org/wiki/File:Sharp_Zaurus_SL-5500G.jpg) by Wusel007, Wikimedia Commons | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) |
| SL-5600 reference photographs (geometry measured, nothing traced) | ["Zaurus SL-5600"](https://www.flickr.com/photos/dronecatcher/51187902024/) by Wayne Sadler and ["Sharp Zaurus SL-5600 (poodle)"](https://www.flickr.com/photos/vickyken/3484833409/) by VickyKenKiyomi | reference only, not distributed |
| C700 reference photograph (geometry measured, nothing traced) | ["Sharp Zaurus SL-C700.jpg"](https://commons.wikimedia.org/wiki/File:Sharp_Zaurus_SL-C700.jpg) by ポリンキ, Wikimedia Commons | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| C700 reference photographs | [HPC.ru SL-C700 review](https://hpc.ru/lib/arts/1927/) by Vladimir Speransky | reference only, not distributed |
| SL-6000 reference photographs | [Sharp product catalogue](https://jp.sharp/products/sl6000/) and [Roberto Innocenti's photographs](https://www.flickr.com/photos/12161791@N00/792844922/) | reference only, not distributed |
| h2200 and its keyboard, h3900, h5550, Collie and C700 keyboard references | the author's own devices and photographs | not distributed |
| Glyph outlines: Mukta | Ek Type | SIL OFL 1.1 |
| Glyph outlines: Open Sans | Steve Matteson | SIL OFL 1.1 |
| Glyph outlines: Noto Sans CJK JP | Google | SIL OFL 1.1 |
| Glyph outlines: Roboto | Google | Apache-2.0 |

HP, Compaq, iPAQ, Pocket PC, Sharp and Zaurus are trademarks of their owners and appear only to identify the devices.

## Licence

The drawings are CC-BY-SA-4.0; the scripts are GPL-2.0-or-later. The texts are in `LICENSES/`, and `REUSE.toml` assigns them per file.
