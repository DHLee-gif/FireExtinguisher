import copy
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from detector import CONFIG_PATH, detect, load_config
from synthetic import HEIGHT, WIDTH, scene


class DetectorTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def assert_line(self, image, offset, angle, offset_tolerance=0.03, angle_tolerance=2.0):
        result = detect(image, self.config)
        self.assertTrue(result.found, result)
        self.assertAlmostEqual(result.offset, offset, delta=offset_tolerance)
        self.assertAlmostEqual(result.angle_deg, angle, delta=angle_tolerance)

    def assert_no_line(self, image):
        result = detect(image, self.config)
        self.assertEqual((result.found, result.offset, result.angle_deg), (False, None, None), result)

    def test_known_offsets_and_angles(self):
        for offset in (-0.7, -0.3, 0.0, 0.3, 0.7):
            for angle in (-30, -10, 0, 10, 30):
                # Skip combinations where the line leaves the image inside the ROI.
                if abs(offset + np.tan(np.radians(angle)) * 240 / 320) > 0.9:
                    continue
                with self.subTest(offset=offset, angle=angle):
                    self.assert_line(scene(offset, angle), offset, angle)

    def test_right_is_positive(self):
        self.assertGreater(detect(scene(0.4, 0), self.config).offset, 0)
        self.assertGreater(detect(scene(0, 15), self.config).angle_deg, 0)

    def test_light_floor_uneven_light_and_noise(self):
        self.assert_line(scene(0.2, 5, floor=(185, 185, 185), line=(245, 245, 245)), 0.2, 5)
        self.assert_line(scene(0.2, 5, gradient=0.4), 0.2, 5, 0.05, 3)
        self.assert_line(scene(-0.2, -5, noise=15), -0.2, -5, 0.05, 3)

    def test_line_widths(self):
        for width in (12, 40, 100):
            with self.subTest(width=width):
                self.assert_line(scene(0.1, 0, line_px=width), 0.1, 0)

    def test_no_line(self):
        for floor in ((0, 0, 0), (70, 70, 70), (200, 200, 200), (255, 255, 255)):
            for noise in (0, 15):
                with self.subTest(floor=floor, noise=noise):
                    self.assert_no_line(scene(floor=floor, noise=noise, draw_line=False))

    def test_colored_lines_are_not_white(self):
        for color in ((0, 0, 220), (220, 60, 0), (0, 220, 220)):
            with self.subTest(color=color):
                self.assert_no_line(scene(line=color))

    def test_round_glare_is_not_a_line(self):
        image = scene(draw_line=False)
        cv2.circle(image, (450, 380), 45, (255, 255, 255), -1)
        self.assert_no_line(image)

    def test_line_wins_over_glare(self):
        image = scene(-0.3, 0)
        cv2.circle(image, (520, 380), 40, (255, 255, 255), -1)
        self.assert_line(image, -0.3, 0)

    def test_crossing_stripe_is_ignored(self):
        image = scene(0.2, 0)
        cv2.rectangle(image, (0, 340), (WIDTH, 370), (235, 235, 235), -1)
        self.assert_line(image, 0.2, 0)

    def test_broken_tilted_line_is_joined(self):
        image = scene(0.1, 15)
        image[345:375] = 70
        self.assert_line(image, 0.1, 15)

    def test_stripe_only_across_is_no_line(self):
        image = scene(draw_line=False)
        cv2.rectangle(image, (0, 340), (WIDTH, 370), (235, 235, 235), -1)
        self.assert_no_line(image)

    def test_bright_floor_beside_dark_object_is_no_line(self):
        # Seen on the real camera: only one side of the bright area is darker.
        image = scene(floor=(200, 200, 200), draw_line=False)
        cv2.rectangle(image, (530, 300), (580, 479), (40, 40, 40), -1)
        self.assert_no_line(image)

    def test_curve_offset_is_measured_near_the_car(self):
        image = scene(draw_line=False)
        for y in range(200, HEIGHT):
            x = round((WIDTH - 1) / 2 + 0.005 * (HEIGHT - 1 - y) ** 2)
            cv2.line(image, (x - 20, y), (x + 20, y), (235, 235, 235), 1)
        result = detect(image, self.config)
        self.assertTrue(result.found)
        self.assertAlmostEqual(result.offset, 0, delta=0.04)
        self.assertGreater(result.angle_deg, 0)

    def test_two_lines_follow_the_previous_one(self):
        for seed in range(10):
            image = np.maximum(scene(-0.5, noise=8, seed=seed), scene(0.5, noise=8, seed=seed + 50))
            for previous in (-0.4, 0.4):
                result = detect(image, self.config, previous)
                self.assertAlmostEqual(result.offset, np.sign(previous) * 0.5, delta=0.03)
                self.assertEqual(result.candidates, 2)

    def test_long_glare_is_not_a_line(self):
        for axes in ((20, 60), (25, 120), (40, 110), (80, 120), (60, 60)):
            with self.subTest(axes=axes):
                image = scene(floor=(110, 110, 110), draw_line=False, noise=4)
                cv2.ellipse(image, (320, 370), axes, 0, 0, 360, (250, 250, 250), -1)
                self.assert_no_line(image)

    def test_tapering_line_is_found(self):
        image = scene(draw_line=False)
        cv2.fillPoly(image, [np.array([[290, 479], [350, 479], [328, 200], [312, 200]])], (235, 235, 235))
        self.assert_line(image, 0, 0)

    def test_does_not_jump_to_another_line(self):
        result = detect(scene(0.5), self.config, -0.5)
        self.assertEqual((result.found, result.offset), (False, None))
        self.assertTrue(detect(scene(-0.4), self.config, -0.5).found)

    def test_above_roi_is_ignored(self):
        image = scene(0.2, 0)
        image[HEIGHT // 2:] = 70
        self.assert_no_line(image)

    def test_color_is_configurable(self):
        for name, floor, line in (("black", (200, 200, 200), (20, 20, 20)),
                                  ("yellow", (70, 70, 70), (0, 220, 220))):
            self.config = copy.deepcopy(self.config)
            self.config["color"] = name
            with self.subTest(color=name):
                self.assert_line(scene(0.3, 10, floor=floor, line=line), 0.3, 10)

    def test_input_is_not_modified_and_may_be_read_only(self):
        image = scene(0.1)
        before = image.copy()
        image.flags.writeable = False
        detect(image, self.config)
        np.testing.assert_array_equal(image, before)

    def test_bad_config_is_rejected(self):
        text = CONFIG_PATH.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.toml"
            for old, new in (('color = "white"', 'color = "pink"'), ("roi_top = 0.5", "roi_top = 1.0"), ("roi_top = 0.5", "roi_top = 0.99"),
                             ("[179, 70, 255]", "[300, 70, 255]"), ("[0, 0, 110]", "[0, 0]"),
                             ("contrast = 20", 'contrast = "x"'), ("contrast = 20", "contrast = 500"),
                             ("max_frame_age_s = 0.2", "max_frame_age_s = inf")):
                self.assertIn(old, text)
                path.write_text(text.replace(old, new), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_config(path)


if __name__ == "__main__":
    unittest.main()
