import math
import struct
import time
import unittest
from pathlib import Path

from lidar_bridge import MeasurementStatus as M
from lidar_bridge import crc16_ccitt_false
from run import CycleBuilder, load_config
from summary import CLEAR, UNKNOWN, oldest_age_ms, summarize

CAPTURE = Path(__file__).parents[1] / "captures" / "COM5_2026-11-16.hex"
CONFIG = {"car_width_mm": 200, "side_margin_mm": 50, "side_lookahead_mm": 500}


def point(x, y, status=M.VALID):
    return (math.degrees(math.atan2(y, x)), status, round(math.hypot(x, y)), None)


# No returns in every direction: every area counts as seen and clear.
SWEEP = [(float(b), M.NO_RETURN, 0xFFFF, None) for b in range(-180, 180, 5)]


class SummaryTests(unittest.TestCase):
    def test_corridor_and_sides(self):
        points = [point(1000, 0), point(600, 140), point(400, 200), point(300, -350), point(-500, 0)]
        s = summarize(points + SWEEP, CONFIG)
        self.assertAlmostEqual(s["front_clear_mm"], 600, delta=2)   # y=140 is inside 150.
        self.assertAlmostEqual(s["right_clear_mm"], 200, delta=2)
        self.assertAlmostEqual(s["left_clear_mm"], 350, delta=2)
        self.assertAlmostEqual(s["nearest_mm"], 447, delta=2)
        self.assertEqual(summarize(points, CONFIG)["front_clear_mm"], UNKNOWN)  # Area not swept.
        self.assertAlmostEqual(s["nearest_bearing_deg"], 26.6, delta=0.2)

    def test_outside_corridor_does_not_block(self):
        self.assertEqual(summarize([point(300, 160), point(-300, -160)] + SWEEP, CONFIG)["front_clear_mm"], CLEAR)

    def test_unknown_clear_and_flags(self):
        self.assertEqual(summarize([], CONFIG)["front_clear_mm"], UNKNOWN)
        front_only = [(float(b), M.NO_RETURN, 0xFFFF, None) for b in range(-60, 60, 5)]
        s = summarize(front_only + [(2.0, M.TOO_CLOSE, 90, None)], CONFIG)
        self.assertEqual((s["front_clear_mm"], s["flags"], s["nearest_mm"]), (CLEAR, 0x03, CLEAR))
        self.assertEqual(s["left_clear_mm"], UNKNOWN)

    def test_partly_swept_area_is_unknown_not_clear(self):
        for points in ([(-170.0, M.NO_RETURN, 0xFFFF, None)], [(80.0, M.NO_RETURN, 0xFFFF, None)],
                       [(float(b), M.NO_RETURN, 0xFFFF, None) for b in range(5, 28)]):
            s = summarize(points, CONFIG)
            self.assertEqual((s["front_clear_mm"], s["left_clear_mm"], s["right_clear_mm"]),
                             (UNKNOWN, UNKNOWN, UNKNOWN))

    def test_age_is_oldest_point_with_margin(self):
        now = time.monotonic()
        self.assertEqual(oldest_age_ms([(0.0, M.VALID, 500, now - 10.0), (1.0, M.VALID, 500, now)], now), 10100)
        self.assertEqual(oldest_age_ms([], now), 0xFFFF)

    def test_startup_revolution_is_not_clear(self):
        records = CycleBuilder(load_config()).feed(bytes.fromhex(CAPTURE.read_text()), time.monotonic())
        self.assertEqual(records[0]["summary"]["right_clear_mm"], UNKNOWN)

    def test_capture_packet(self):
        records = CycleBuilder(load_config()).feed(bytes.fromhex(CAPTURE.read_text()), time.monotonic())
        record = records[2]
        packet = bytes.fromhex(record["summary_packet"])
        fields = struct.unpack("<2sBBHHHHHhBHH", packet)
        s = record["summary"]
        self.assertEqual(len(packet), 21)
        self.assertEqual(fields[:9], (b"\xC3\x5C", 1, 0, record["sequence"], s["front_clear_mm"],
                                      s["left_clear_mm"], s["right_clear_mm"], s["nearest_mm"],
                                      round(s["nearest_bearing_deg"] * 10)))
        self.assertEqual(fields[11], crc16_ccitt_false(packet[:19]))
        builder = CycleBuilder(load_config())
        points = []
        builder._finish = lambda status, keep=builder._finish: (points.extend(builder.cycle.points), keep(status))[1]
        builder.feed(bytes.fromhex(CAPTURE.read_text()), time.monotonic())
        self.assertTrue(points)
        self.assertGreater(s["nearest_mm"], 0)


if __name__ == "__main__":
    unittest.main()
