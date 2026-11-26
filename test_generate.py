"""Focused CLI, validation and reproducibility tests (python3 -m unittest -v)."""
# SPDX-FileCopyrightText: 2026 Koen Kooi
# SPDX-License-Identifier: GPL-2.0-or-later

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

import generate as generator


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.directory = generator.REPOSITORY / f".generator-test-{uuid4().hex}"
        self.directory.mkdir()
        self.addCleanup(shutil.rmtree, self.directory)

    def cli(self, *args, success, no_site=False, env=None):
        command = [sys.executable]
        if no_site:
            command.append("-S")
        result = subprocess.run(
            command + [str(generator.REPOSITORY / "generate.py"), *map(str, args)],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        sentinel = "SUCCESS" if success else "FAILURE"
        self.assertEqual(result.stdout.splitlines()[-1], sentinel)
        self.assertEqual([line for line in (result.stdout + result.stderr).splitlines()
                          if line in ("SUCCESS", "FAILURE")], [sentinel])
        return result

    @staticmethod
    def drawing():
        return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 1400">'
                '<rect id="screen" x="137.5" y="244.75" width="525" height="700"/>'
                '</svg>').encode()

    def test_cli_failures_have_one_final_sentinel_and_no_outputs(self):
        for args in ((), ("unknown",), ("h2200",), ("--unknown",),
                     ("sl-c700", "--output", self.directory / "both.svg"),
                     ("h3900", "--output", self.directory / "wrong.txt"),
                     ("h3900", "--fonts", self.directory, "--output-dir", self.directory)):
            with self.subTest(args=args):
                self.cli(*args, success=False)
        result = self.cli("h3900", "--output-dir", self.directory, success=False, no_site=True)
        self.assertIn("fontTools is required", result.stderr)
        self.assertEqual(list(self.directory.iterdir()), [])
        self.cli("--list", success=True, no_site=True)
        self.cli("--help", success=True, no_site=True)

    def test_validation_rejects_broken_screen_and_ids(self):
        drawing = self.drawing()
        model = generator.MODELS["h3900"]
        generator.validate_svg(drawing, model)
        invalid = (
            drawing.replace(b'width="525"', b'width="524"'),
            drawing.replace(b'<rect ', b'<g id="screen"/><rect '),
            drawing.replace(b'<rect ', b'<rect transform="translate(1 0)" '),
            drawing.replace(b'<rect ', b'<g transform="scale(2)"><rect ').replace(b'</svg>', b'</g></svg>'),
            drawing.replace(b'id="screen"', b'id="not-screen"'),
            drawing.replace(b'</svg>', b''),
        )
        for value in invalid:
            with self.subTest(drawing=value):
                with self.assertRaises((ValueError, generator.ET.ParseError)):
                    generator.validate_svg(value, model)

    def test_staging_failure_keeps_existing_outputs_and_removes_pending_files(self):
        first = self.directory / "first.svg"
        first.write_bytes(b"existing artwork")
        blocked = self.directory / "blocked.svg"
        blocked.mkdir()
        model = generator.MODELS["h3900"]
        with self.assertRaises(IsADirectoryError):
            generator.write_outputs(
                {"first": model, "blocked": model},
                {"first": self.drawing(), "blocked": self.drawing()},
                {"first": first, "blocked": blocked},
            )
        self.assertEqual(first.read_bytes(), b"existing artwork")
        self.assertEqual(set(self.directory.iterdir()), {first, blocked})

    def test_check_detects_missing_and_changed_outputs_without_writing(self):
        output = self.directory / "checked.svg"
        for existing in (None, self.drawing() + b"\n"):
            with self.subTest(existing=existing):
                if existing is not None:
                    output.write_bytes(existing)
                with patch.object(generator, "generate", return_value={"h3900": self.drawing()}):
                    with contextlib.redirect_stdout(io.StringIO()) as stdout:
                        with contextlib.redirect_stderr(io.StringIO()):
                            status = generator.main(["h3900", "--check", "--output", str(output)])
                self.assertNotEqual(status, 0)
                self.assertEqual(stdout.getvalue().splitlines()[-1], "FAILURE")
                self.assertEqual(output.read_bytes() if output.exists() else None, existing)

    def test_partial_replacement_reports_failure_not_success(self):
        paths = [self.directory / generator.MODELS[name].path for name in ("h3900", "h5550")]
        for path in paths:
            path.parent.mkdir()
            path.write_bytes(b"existing artwork")
        replace = os.replace

        def fail_second(source, destination):
            if destination == paths[1]:
                raise OSError("simulated final replacement failure")
            replace(source, destination)

        drawings = dict.fromkeys(("h3900", "h5550"), self.drawing())
        with patch.object(generator, "generate", return_value=drawings):
            with patch.object(generator.os, "replace", side_effect=fail_second):
                with contextlib.redirect_stdout(io.StringIO()) as stdout:
                    with contextlib.redirect_stderr(io.StringIO()):
                        status = generator.main(["h3900", "h5550", "--output-dir", str(self.directory)])
        self.assertNotEqual(status, 0)
        self.assertEqual(stdout.getvalue().splitlines(), ["FAILURE"])
        self.assertEqual(paths[0].read_bytes(), self.drawing())
        self.assertEqual(paths[1].read_bytes(), b"existing artwork")
        self.assertEqual(list(self.directory.rglob("*.pending")), [])

    def test_all_artwork_reproduces_and_selections_work(self):
        fonts = Path(os.environ.get("IPAQ_FONTS", "/Library/Fonts"))
        required = {filename for model in generator.MODELS.values() for filename in model.fonts}
        missing = sorted(filename for filename in required if not (fonts / filename).is_file())
        if importlib.util.find_spec("fontTools") is None or missing:
            self.skipTest(f"artwork integration needs fontTools and reference fonts in {fonts}; missing: {missing}")
        self.cli("all", "--output-dir", self.directory, "--fonts", fonts, success=True)
        environment = dict(os.environ, IPAQ_FONTS=str(fonts))
        self.cli("all", "--check", "--output-dir", self.directory, success=True, env=environment)
        for model in generator.MODELS.values():
            self.assertEqual((self.directory / model.path).read_bytes(),
                             (generator.REPOSITORY / model.path).read_bytes(), model.path)
        self.cli("sl-c700", "--check", "--output-dir", self.directory, "--fonts", fonts, success=True)
        single = self.directory / "single.svg"
        self.cli("sl-c700-pda", "--output", single, "--fonts", fonts, success=True)
        self.assertEqual(single.read_bytes(), (self.directory / generator.MODELS["sl-c700-pda"].path).read_bytes())
        for view in ("front", "away", "swivel"):
            self.cli("all", "--camera", view, "--output-dir", self.directory, "--fonts", fonts, success=True)
            self.cli("all", "--camera", view, "--check", "--output-dir", self.directory, "--fonts", fonts, success=True)
            for model in generator.select_models(["all"], view).values():
                root = generator.validate_svg((self.directory / model.path).read_bytes(), model)
                drawable = [node for node in root if node.tag.split("}")[-1]
                            not in ("title", "desc", "defs", "style", "view", "metadata")]
                if model.camera_pose.layer == "behind":
                    self.assertEqual(drawable[0].get("id"), "photosmart-camera")
        for camera in (None, "front"):
            arguments = ["all", "--keyboard", "--output-dir", self.directory, "--fonts", fonts]
            if camera:
                arguments += ["--camera", camera]
            self.cli(*arguments, success=True)
            self.cli(*arguments, "--check", success=True)
        self.cli("sl-c700-pda", "--keyboard", "--check", "--output-dir", self.directory,
                 "--fonts", fonts, success=True)
        for model in generator.MODELS.values():
            self.assertEqual((self.directory / model.path).read_bytes(),
                             (generator.REPOSITORY / model.path).read_bytes(), model.path)

    def test_camera_ports_and_manual_compositions_need_no_font_dependency(self):
        self.cli("camera", "--output-dir", self.directory, success=True, no_site=True)
        self.cli("camera", "--check", "--output-dir", self.directory, success=True, no_site=True)
        for model in generator.CAMERA_MODELS.values():
            self.assertEqual((self.directory / model.path).read_bytes(),
                             (generator.REPOSITORY / model.path).read_bytes())
        source = generator.REPOSITORY / generator.MANUAL_MODELS["h2200"].source
        original = source.read_bytes()
        base = generator.ET.fromstring(original)
        self.assertIsNone(base.get("width"))
        self.assertIsNone(base.get("height"))
        for view in ("front", "away", "swivel"):
            self.cli("h2200", "--camera", view, "--output-dir", self.directory, success=True, no_site=True)
            self.cli("h2200", "--camera", view, "--check", "--output-dir", self.directory,
                     success=True, no_site=True)
            model = generator.select_models(["h2200"], view)["h2200"]
            self.assertEqual(model.path, f"h2200/ipaq-h2200-camera-{view}.svg")
            root = generator.validate_svg((self.directory / model.path).read_bytes(), model)
            self.assertIsNone(root.get("width"))
            self.assertIsNone(root.get("height"))
        self.assertEqual(source.read_bytes(), original)
        camera_dir = generator.REPOSITORY / "accesoires/hp-photosmart-camera"
        for filename in ("on-h2200.svg", "on-h2200-away.svg", "on-h2200-swivel.svg"):
            self.assertFalse((camera_dir / filename).exists())
        self.assertFalse((self.directory / generator.MANUAL_MODELS["h2200"].source).exists())

    def test_c700_shortcuts_share_glyphs_and_lid_rotation(self):
        strips = {}
        for view in ("laptop", "pda"):
            root = generator.ET.parse(generator.REPOSITORY / generator.MODELS[f"sl-c700-{view}"].path).getroot()
            strips[view] = {}
            for name in ("home", "mail", "address", "calendar", "clock"):
                target = root.find(f".//*[@id='touch-{name}']")
                self.assertIsNotNone(target)
                glyph = target.find("./*[@data-shortcut]")
                self.assertIsNotNone(glyph)
                angle = float(generator.re.fullmatch(r"rotate\(([-.\d]+)\)", glyph.attrib.pop("transform"))[1])
                glyph.tail = None
                strips[view][name] = (angle, generator.ET.tostring(glyph))
        for name, (laptop_angle, glyph) in strips["laptop"].items():
            pda_angle, folded_glyph = strips["pda"][name]
            with self.subTest(shortcut=name):
                self.assertEqual(glyph, folded_glyph)
                self.assertEqual(pda_angle - laptop_angle, 90)

    def test_ipaq_leds_are_recolourable_fills(self):
        expected = {
            "h2200": ("bluetooth", "power"),
            "h3900": ("bluetooth", "power"),
            "h5550": ("bluetooth", "power", "wlan"),
            "hx2700": ("radio", "charge"),
            "hx4700": ("wireless", "notification", "power"),
        }
        for model, leds in expected.items():
            path = (generator.MANUAL_MODELS.get(model) or generator.MODELS[model]).path
            root = generator.ET.parse(generator.REPOSITORY / path).getroot()
            for name in leds:
                with self.subTest(model=model, led=name):
                    led = root.find(f".//*[@id='led-{name}']")
                    self.assertIsNotNone(led)
                    self.assertRegex(led.get("fill"), r"^#[0-9a-f]{6}$")

    def test_camera_failures_do_not_overwrite_base_or_guess_missing_poses(self):
        output = self.directory / "ipaq-h2200.svg"
        output.write_bytes(b"manual original")
        for args in (("h2200", "--camera", "front", "--output", output),
                     ("h2200", "--camera", "above", "--output-dir", self.directory),
                     ("camera-front", "--camera", "front", "--output-dir", self.directory)):
            self.cli(*args, success=False)
        self.assertEqual(output.read_bytes(), b"manual original")
        with patch.dict(generator.CAMERA_POSES, {}, clear=True):
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                with contextlib.redirect_stderr(io.StringIO()) as stderr:
                    status = generator.main(["all", "--camera", "front", "--output-dir", str(self.directory)])
        self.assertNotEqual(status, 0)
        self.assertEqual(stdout.getvalue().splitlines(), ["FAILURE"])
        self.assertIn("no researched SD-slot camera pose", stderr.getvalue())
        self.assertEqual(list(self.directory.iterdir()), [output])
        variant = self.directory / "custom-camera-front.svg"
        self.cli("h2200", "--camera", "front", "--output", variant, success=True, no_site=True)
        self.cli("h2200", "--camera", "front", "--check", "--output", variant, success=True, no_site=True)

    def test_accessory_namespace_rewrites_css_href_and_smil_references(self):
        root = generator.ET.fromstring('''<svg xmlns="http://www.w3.org/2000/svg"
            xmlns:xlink="http://www.w3.org/1999/xlink" aria-labelledby="title">
            <title id="title">Camera</title><defs><linearGradient id="paint"/></defs>
            <style>#head:hover { fill: url("#paint") }</style>
            <g id="head" data-in="paint" fill="url(#paint)"><animate id="turn"
            begin="head.click; turn.end+1s" end="head.mouseout"/></g>
            <use href="#head" xlink:href="#head"/></svg>''')
        generator.namespace_ids(root, "photosmart-")
        nodes = {node.get("id"): node for node in root.iter() if node.get("id")}
        self.assertEqual(set(nodes), {"photosmart-title", "photosmart-paint", "photosmart-head", "photosmart-turn"})
        self.assertEqual(root.get("aria-labelledby"), "photosmart-title")
        head = nodes["photosmart-head"]
        self.assertEqual(head.get("data-in"), "photosmart-paint")
        self.assertEqual(head.get("fill"), "url(#photosmart-paint)")
        self.assertEqual(nodes["photosmart-turn"].get("begin"), "photosmart-head.click; photosmart-turn.end+1s")
        self.assertEqual(nodes["photosmart-turn"].get("end"), "photosmart-head.mouseout")
        style = root.find(f"{{{generator.SVG_NS}}}style").text
        self.assertIn('#photosmart-head:hover', style)
        self.assertIn('url("#photosmart-paint")', style)
        use = root.find(f"{{{generator.SVG_NS}}}use")
        self.assertEqual(set(use.attrib.values()), {"#photosmart-head"})

    def test_physical_compatibility_resolves_sleeve_slots(self):
        card = "buffalo-wli-cf-s11g"
        devices = generator.json.loads(
            (generator.REPOSITORY / "accesoires/compatibility.json").read_text())["devices"]
        self.assertNotIn("h3100", devices)
        self.assertNotIn("h3700", devices)
        self.assertNotIn("h3800", devices)
        for device in ("h2200", "hx2700", "hx4700", "sl-5500", "sl-6000", "sl-c700-pda"):
            self.assertIn(card, generator.compatible_accessories(device))
            self.assertNotIn("navman-gps-sleeve", generator.compatible_accessories(device))
        for device in ("h36xx", "h39xx", "h5xxx", "h3600", "h3900", "h5550"):
            self.assertNotIn(card, generator.compatible_accessories(device))
            for sleeve in ("cf-sleeve", "navman-gps-sleeve"):
                self.assertIn(card, generator.compatible_accessories(device, [sleeve]))
        self.assertIn("h2200-keyboard", generator.compatible_accessories("h2200"))
        self.assertNotIn("h2200-keyboard", generator.compatible_accessories("h3900"))
        first = generator.compatible_accessories("h3900", [card, "cf-sleeve"])
        second = generator.compatible_accessories("h3900", ["cf-sleeve", card])
        self.assertEqual(first, second)
        self.assertNotIn("asus-wl110", first)

    def test_physical_compatibility_rejects_impossible_attachments(self):
        for device, attached in (
            ("missing", []),
            ("h3900", ["missing"]),
            ("h3900", ["h2200-keyboard"]),
            ("h3900", ["buffalo-wli-cf-s11g"]),
            ("h3900", ["cf-sleeve", "navman-gps-sleeve"]),
            ("h2200", ["buffalo-wli-cf-s11g", "asus-wl110"]),
            ("h2200", ["h2200-keyboard", "h2200-keyboard"]),
        ):
            with self.subTest(device=device, attached=attached):
                with self.assertRaises(ValueError):
                    generator.compatible_accessories(device, attached)
        self.cli("--compatible", "h3900", "--with-accessory", "cf-sleeve", success=True)
        self.cli("--with-accessory", "cf-sleeve", success=False)
        self.cli("--compatible", "h2200", "--keyboard", success=False)

    def test_catalog_drawings_expose_matching_compatibility_tags(self):
        catalog = generator.json.loads(
            (generator.REPOSITORY / "accesoires/compatibility.json").read_text())
        for name, item in catalog["accessories"].items():
            if item["drawing"] is None:
                continue
            with self.subTest(accessory=name):
                root = generator.ET.parse(generator.REPOSITORY / item["drawing"]).getroot()
                self.assertEqual(root.get("data-accessory"), name)
                self.assertEqual(root.get("data-requires", "").split(), item["requires"])
                self.assertEqual(root.get("data-provides", "").split(), item["provides"])

    def test_accessory_indicator_windows_are_addressable(self):
        indicators = {
            "buffalo-wli-cf-s11g": ("led-power", "led-active"),
            "sandisk-connectplus": ("led-link",),
            "ipaq-keyboard-sleeve": ("led-status",),
        }
        for accessory, expected_ids in indicators.items():
            path = generator.REPOSITORY / generator.ACCESSORY_MODELS[accessory].path
            root = generator.ET.parse(path).getroot()
            elements = {element.get("id"): element for element in root.iter() if element.get("id")}
            for identity in expected_ids:
                with self.subTest(accessory=accessory, indicator=identity):
                    self.assertIn(identity, elements)
                    self.assertTrue(elements[identity].get("fill"))

    def test_nslu2_exposes_editable_indicators_and_rejects_handheld_variants(self):
        root = generator.ET.parse(
            generator.REPOSITORY / generator.APPLIANCE_MODELS["nslu2-front"].path).getroot()
        elements = {element.get("id"): element for element in root.iter() if element.get("id")}
        self.assertNotIn("screen", elements)
        self.assertIn("button-power", elements)
        for identity in generator.NSLU2_LEDS:
            with self.subTest(indicator=identity):
                self.assertNotIn("url(", elements[identity].get("fill"))
        elements["led-ready"].set("fill", "url(#nslu2-glass)")
        broken = generator.ET.tostring(root, encoding="unicode")
        with self.assertRaisesRegex(ValueError, "led-ready"):
            generator.validate_svg(broken, generator.APPLIANCE_MODELS["nslu2-front"])
        for option in (("--camera", "front"), ("--keyboard",),
                       ("--sleeve", "navman-gps-sleeve")):
            with self.subTest(option=option):
                self.cli("nslu2-front", *option, "--output-dir", self.directory, success=False)

    def test_buffalo_antenna_hole_is_transparent(self):
        if shutil.which("rsvg-convert") is None or importlib.util.find_spec("PIL") is None:
            self.skipTest("transparency check needs rsvg-convert and Pillow")
        from PIL import Image
        path = generator.REPOSITORY / generator.ACCESSORY_MODELS["buffalo-wli-cf-s11g"].path
        result = subprocess.run(
            ["rsvg-convert", "-w", "460", str(path)], capture_output=True, check=True)
        with Image.open(io.BytesIO(result.stdout)) as image:
            alpha = image.convert("RGBA").getchannel("A")
            self.assertEqual(alpha.getpixel((52, 87)), 0)
            self.assertEqual(alpha.getpixel((90, 87)), 255)

    def test_composition_preserves_all_screens_and_expands_slider_fragments(self):
        # Synthetic side pose exercises composition, not an assertion about device slots.
        pose = generator.CameraPose(-100, 80, 1.08, rotation=90)
        for name, base in generator.MODELS.items():
            with self.subTest(model=name):
                drawing = (generator.REPOSITORY / base.path).read_bytes()
                composed = generator.compose_camera(drawing, "swivel", pose)
                model = generator.replace(base, camera="swivel", camera_pose=pose)
                root = generator.validate_svg(composed, model)
                ids = {node.get("id"): node for node in root.iter() if node.get("id")}
                self.assertEqual(sum(node.get("id") == "screen" for node in root.iter()), 1)
                self.assertLess(float(root.get("viewBox").split()[0]), 0)
                if model.slider:
                    self.assertIn(ids["art"], list(root))
                    self.assertIn(ids["open"], list(root))
                    self.assertIn(ids["closed"], list(root))
                    self.assertLess(list(root).index(ids["open"]), list(root).index(ids["art"]))
                    for fragment in ("open", "closed"):
                        expected = generator.expanded_viewbox(
                            (0, 40, 800, model.slider[1] if fragment == "open" else 1380), pose.bounds())
                        self.assertEqual(ids[fragment].get("viewBox"), generator.viewbox_text(expected))

    def test_keyboard_and_combined_variants_preserve_the_manual_frame(self):
        fonts = Path(os.environ.get("IPAQ_FONTS", "/Library/Fonts"))
        filenames = ("OpenSans_Regular.ttf", "OpenSans_Bold.ttf")
        if importlib.util.find_spec("fontTools") is None or any(not (fonts / name).is_file() for name in filenames):
            self.skipTest("keyboard integration needs fontTools and Open Sans regular/bold reference fonts")
        source = generator.REPOSITORY / generator.MANUAL_MODELS["h2200"].source
        original = source.read_bytes()
        for camera in (None, "front", "away", "swivel"):
            arguments = ["h2200", "--keyboard", "--output-dir", self.directory, "--fonts", fonts]
            if camera:
                arguments += ["--camera", camera]
            self.cli(*arguments, success=True)
            self.cli(*arguments, "--check", success=True)
            model = generator.select_models(["h2200"], camera, keyboard=True)["h2200"]
            result = (self.directory / model.path).read_bytes()
            root = generator.validate_svg(result, model)
            self.assertIsNone(root.get("width"))
            self.assertIsNone(root.get("height"))
            ids = {node.get("id"): node for node in root.iter() if node.get("id")}
            keys = {identity for identity in ids if identity.startswith("key-")}
            self.assertEqual(len(keys), 37)
            self.assertTrue({"key-fn-orange", "key-fn-blue", "key-tab", "key-space"} <= keys)
            self.assertEqual(tuple(ids["screen"].get(key) for key in ("x", "y", "width", "height")),
                             ("137.5", "168", "525", "700"))
            self.assertIn(ids["addon-keyboard"], list(root))
            self.assertIsNone(ids["addon-keyboard"].get("transform"))
            if camera:
                self.assertIn(f"-keyboard-camera-{camera}.svg", model.path)
            else:
                self.assertEqual(root.get("viewBox"), "0 0 800 1400")
                standalone = generator.ET.parse(
                    generator.REPOSITORY / generator.ACCESSORY_MODELS["h2200-keyboard"].path).getroot()
                self.assertEqual(standalone.get("data-frame"), "h2200/ipaq-h2200.svg")
                for element in (standalone.find(f"{{{generator.SVG_NS}}}g"), ids["addon-keyboard"]):
                    element.tail = None
                self.assertEqual(generator.ET.tostring(standalone.find(f"{{{generator.SVG_NS}}}g")),
                                 generator.ET.tostring(ids["addon-keyboard"]))
        self.assertEqual(source.read_bytes(), original)

    def test_keyboard_rejects_other_models_and_nonvariant_outputs(self):
        protected = self.directory / "ipaq-h2200.svg"
        protected.write_bytes(b"manual original")
        for arguments in (
            ("h3900", "--keyboard", "--output-dir", self.directory),
            ("camera-front", "--keyboard", "--output-dir", self.directory),
            ("h2200", "--keyboard", "--output", protected),
            ("h2200", "--keyboard", "--camera", "front", "--output", self.directory / "on-h2200.svg"),
            ("h2200", "--keyboard", "--camera", "front", "--output", self.directory / "ipaq-h2200-keyboard.svg"),
        ):
            self.cli(*arguments, success=False)
        self.assertEqual(list(self.directory.iterdir()), [protected])
        self.assertEqual(protected.read_bytes(), b"manual original")

    def test_sleeves_seat_each_ipaq_at_the_photographed_rail_offset(self):
        fonts = Path(os.environ.get("IPAQ_FONTS", "/Library/Fonts"))
        selected = {(device, sleeve): model for sleeve in generator.SLEEVE_FITS
                    for device, model in generator.select_models(["all"], sleeve=sleeve).items()}
        required = {filename for model in selected.values() for filename in model.fonts}
        missing = sorted(filename for filename in required if not (fonts / filename).is_file())
        if importlib.util.find_spec("fontTools") is None or missing:
            self.skipTest(f"sleeve composition needs fontTools and fonts in {fonts}; missing: {missing}")
        self.assertEqual({device for device, _ in selected}, {"h3900", "h5550"})
        offsets = {}
        for (device, sleeve), model in selected.items():
            drawing = generator.generate({device: model}, fonts)[device]
            root = generator.validate_svg(drawing, model)
            ids = {node.get("id"): node for node in root.iter() if node.get("id")}
            values = ids["sleeve-front"].get("transform").replace("(", " ").replace(")", " ").split()
            y, scale = float(values[2]), float(values[4])
            fit = generator.SLEEVE_FITS[sleeve]
            rail_top = y + fit.rail_top * scale
            offsets.setdefault(sleeve, []).append(rail_top - generator.SLEEVE_BODY_TOPS[device])
            if device == fit.reference:
                self.assertAlmostEqual(y, fit.y, places=2)
            front = list(ids["sleeve-front"].iter())
            self.assertEqual(sum((node.get("id") or "").startswith("sleeve-key-") for node in front),
                             41 if fit.keyboard else 0)
        for sleeve, values in offsets.items():
            self.assertAlmostEqual(values[0], values[1], places=2, msg=sleeve)
        for arguments in (("h3900", "--sleeve", "navman-gps-sleeve", "--camera", "front"),
                          ("hx4700", "--sleeve", "ipaq-keyboard-sleeve")):
            self.cli(*arguments, "--output-dir", self.directory, success=False, no_site=True)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_keyboard_selection_uses_each_devices_available_configuration(self):
        keyboards = {"sl-5500", "sl-5600", "sl-6000", "sl-c700-laptop", "h2200"}
        self.assertEqual(set(generator.select_models(["all"], keyboard=True)), keyboards)
        self.assertEqual(set(generator.select_models(["all"], "front", keyboard=True)), keyboards)
        self.assertEqual(set(generator.select_models(["all"], "front")),
                         set(generator.MODELS) | {"h2200"})
        for view in ("sl-c700", "sl-c700-pda", "sl-c700-laptop"):
            selected = generator.select_models([view], keyboard=True)
            self.assertEqual(list(selected), ["sl-c700-laptop"])
            self.assertEqual(selected["sl-c700-laptop"].screen, (255, 92, 700, 525))

    def test_custom_outputs_cannot_overwrite_another_models_frame_or_accessory(self):
        cases = (
            ("h3900", (), "ipaq-h2200.svg"),
            ("sl-6000", ("--keyboard",), "ipaq-h2200-keyboard.svg"),
            ("sl-6000", ("--camera", "front"), "h5550-framed-template-camera-front.svg"),
        )
        for model, options, filename in cases:
            with self.subTest(model=model, options=options):
                result = self.cli(model, *options, "--output", self.directory / filename,
                                  success=False, no_site=True)
                self.assertIn("reserved for another model or variant", result.stderr)
        self.assertEqual(list(self.directory.iterdir()), [])
        self.cli("h2200", "--camera", "front", "--output",
                 self.directory / "ipaq-h2200-camera-front.svg", success=True, no_site=True)

    def test_open_keyboard_variants_preserve_screens_and_fragment_canvases(self):
        for name, base in generator.MODELS.items():
            if not base.slider:
                continue
            for camera in (None, "front"):
                with self.subTest(model=name, camera=camera):
                    model = generator.select_models([name], camera, keyboard=True)[name]
                    drawing = generator.open_keyboard((generator.REPOSITORY / base.path).read_bytes(), base.slider)
                    if camera:
                        drawing = generator.compose_camera(drawing, camera, model.camera_pose)
                    root = generator.validate_svg(drawing, model)
                    opened = root.find(f"{{{generator.SVG_NS}}}view[@id='open']")
                    self.assertEqual(root.get("viewBox"), opened.get("viewBox"))
                    self.assertIsNotNone(root.find(f"{{{generator.SVG_NS}}}view[@id='closed']"))


if __name__ == "__main__":
    unittest.main()
