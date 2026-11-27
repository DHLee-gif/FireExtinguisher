import struct
import time
import unittest
from pathlib import Path

import numpy as np

from detector import Detection, decode, detect, letterbox, load_config, load_model
from packet import FireStatus, crc16_ccitt_false, encode
from run import FireProcessor

# Tests use one-class synthetic outputs and fixed thresholds, independent of the deployed model.
CONFIG = {**load_config(), "fire_class": 0, "score_threshold": 0.5}
DUMMY_MODEL = Path(__file__).with_name("data") / "dummy_yolo.onnx"
FIRE = Detection(x=0.5, y=0.75, width=0.2, height=0.25, score=0.87)


def unpack(packet_hex):
    return struct.unpack("<2sBBHhHHBBBBHHH", bytes.fromhex(packet_hex))


def yolo_output(boxes, classes=1):
    """boxes: (cx, cy, w, h, score) in 320x320 model pixels -> (1, 4 + classes, N)."""
    output = np.zeros((1, 4 + classes, max(1, len(boxes))), np.float32)
    for i, (cx, cy, w, h, score) in enumerate(boxes):
        output[0, :5, i] = (cx, cy, w, h, score)
    return output


class DecodeTest(unittest.TestCase):
    # 640x480 picture in a 320 input: scale 0.5, 40 px gray band at top and bottom.
    def decode(self, boxes, **changes):
        return decode(yolo_output(boxes), {**CONFIG, **changes}, 0.5, 0, 40, 640, 480)

    def test_letterbox_padding(self):
        canvas, scale, left, top = letterbox(np.zeros((480, 640, 3), np.uint8), 320)
        self.assertEqual((canvas.shape, scale, left, top), ((320, 320, 3), 0.5, 0, 40))
        self.assertEqual(canvas[0, 0, 0], 114)

    def test_box_maps_back_to_picture(self):
        # Right half, lower part of the picture: center (480, 360) px -> model (240, 220).
        [found] = self.decode([(240, 220, 32, 40, 0.9)])
        self.assertAlmostEqual(found.x, 0.5, places=3)
        self.assertAlmostEqual(found.y, 0.75, places=3)
        self.assertAlmostEqual(found.width, 0.1, places=3)
        self.assertAlmostEqual(found.height, 80 / 480, places=3)

    def test_low_scores_and_duplicates_dropped(self):
        found = self.decode([(100, 100, 30, 30, 0.9), (101, 100, 30, 30, 0.8), (250, 200, 20, 20, 0.3)])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].score, 0.9)

    def test_left_is_negative(self):
        [found] = self.decode([(40, 160, 20, 20, 0.9)])
        self.assertLess(found.x, -0.5)

    def test_nothing(self):
        self.assertEqual(self.decode([]), [])

    def test_wrong_class_number_is_an_error_not_no_fire(self):
        with self.assertRaises(ValueError):
            self.decode([(100, 100, 30, 30, 0.9)], fire_class=3)


class ModelTest(unittest.TestCase):
    def test_onnx_model_runs_with_opencv(self):
        detections = detect(load_model(DUMMY_MODEL), np.zeros((480, 640, 3), np.uint8), CONFIG)
        self.assertEqual(len(detections), 1)  # 100 identical boxes -> one after NMS
        self.assertAlmostEqual(detections[0].x, 0.0, places=3)
        self.assertAlmostEqual(detections[0].y, 0.5, places=3)
        self.assertAlmostEqual(detections[0].score, 0.9, places=3)

    def test_missing_model(self):
        with self.assertRaises(FileNotFoundError):
            load_model(Path("no_such_model.onnx"))


class ConfirmTest(unittest.TestCase):
    def setUp(self):
        self.processor = FireProcessor({**CONFIG, "window": 5, "confirm_hits": 3})

    def feed(self, seen):
        return self.processor.process([FIRE] if seen else [], time.monotonic_ns(), 0.05)

    def test_single_flash_is_only_suspect(self):
        self.assertEqual(self.feed(True)["status"], "SUSPECT")
        self.assertEqual(self.feed(False)["status"], "SUSPECT")
        self.assertFalse(self.feed(False)["fire"])

    def test_confirmed_after_enough_hits_and_held_until_window_is_empty(self):
        statuses = [self.feed(s)["status"] for s in (True, False, True, True)]
        self.assertEqual(statuses, ["SUSPECT", "SUSPECT", "SUSPECT", "FIRE"])
        # Short misses keep it confirmed; a whole window of misses ends it.
        statuses = [self.feed(False)["status"] for _ in range(5)]
        self.assertEqual(statuses, ["FIRE", "FIRE", "FIRE", "FIRE", "NO_FIRE"])

    def test_no_fire_vs_no_value(self):
        record = self.feed(False)
        self.assertEqual((record["status"], record["fire"]), ("NO_FIRE", False))
        for status in (FireStatus.NO_FRAME, FireStatus.ERROR, FireStatus.NO_MODEL):
            record = self.processor.unknown(status)
            self.assertIsNone(record["fire"])
            self.assertEqual(unpack(record["packet"])[2], status)

    def test_unknown_resets_confirmation(self):
        for _ in range(3):
            self.feed(True)
        self.processor.unknown(FireStatus.NO_FRAME)
        self.assertEqual(self.feed(True)["status"], "SUSPECT")

    def test_position_kept_from_last_sighting(self):
        for _ in range(3):
            self.feed(True)
        record = self.feed(False)
        self.assertEqual(record["status"], "FIRE")
        self.assertEqual(record["target"]["x"], 0.5)
        fields = unpack(record["packet"])
        self.assertEqual(fields[4], 500)
        self.assertNotEqual(fields[11], 0xFFFF)  # seen_ms tells it is from an earlier frame


class PacketTest(unittest.TestCase):
    def test_bytes(self):
        packet = encode(FireStatus.FIRE, 0x1234, FIRE, 0.1, 4, 5, 2, 0.05)
        self.assertEqual(len(packet), 22)
        fields = struct.unpack("<2sBBHhHHBBBBHHH", packet)
        self.assertEqual(fields[:13], (b"\xC3\x6C", 1, 0, 0x1234, 500, 750, 50, 87, 4, 5, 2, 100, 50))
        self.assertEqual(fields[13], crc16_ccitt_false(packet[:20]))

    def test_no_target_fields(self):
        fields = struct.unpack("<2sBBHhHHBBBBHHH", encode(FireStatus.NO_MODEL, 1, None, None, 0, 5, 0, None))
        self.assertEqual(fields[4:8], (0x7FFF, 0xFFFF, 0xFFFF, 0))
        self.assertEqual((fields[11], fields[12]), (0xFFFF, 0xFFFF))

    def test_crc_standard_vector(self):
        self.assertEqual(crc16_ccitt_false(b"123456789"), 0x29B1)


if __name__ == "__main__":
    unittest.main()
