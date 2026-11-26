import struct
import time
import unittest

from common.framebus import Frame
from detector import LineResult, load_config
from packet import LineStatus, crc16_ccitt_false, encode
from run import LineProcessor
from synthetic import scene


def decode(packet):
    return struct.unpack("<2sBBHhhhhhBBbHHH", packet)


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.processor = LineProcessor(load_config())

    def frame(self, **kwargs):
        return Frame(scene(**kwargs), 0, time.monotonic_ns())

    def test_crc_standard_vector(self):
        self.assertEqual(crc16_ccitt_false(b"123456789"), 0x29B1)

    def test_packet_bytes(self):
        track = {"smooth_offset": -0.2, "smooth_angle_deg": 11.0, "offset_rate": 0.5,
                 "last_side": -1, "lost_ms": 0}
        packet = encode(LineStatus.FOUND, LineResult(True, -0.25, 12.34, 0.9, 1), 0x1234, 0.05, track)
        self.assertEqual(len(packet), 25)
        self.assertEqual(decode(packet)[:14], (b"\xC3\x4C", 2, 0, 0x1234, -250, 1234,
                                               -200, 1100, 500, 90, 1, -1, 0, 50))
        self.assertEqual(decode(packet)[14], crc16_ccitt_false(packet[:23]))

    def test_image_to_packet(self):
        fields = decode(bytes.fromhex(self.processor.process(self.frame(offset=0.3, angle_deg=10))["packet"]))
        self.assertEqual(fields[2], LineStatus.FOUND)
        self.assertAlmostEqual(fields[4], 300, delta=20)
        self.assertAlmostEqual(fields[5], 1000, delta=150)

    def test_no_line_and_no_frame_differ_and_carry_no_position(self):
        for record, status in ((self.processor.process(self.frame(draw_line=False)), LineStatus.NO_LINE),
                               (self.processor.no_frame(), LineStatus.NO_FRAME)):
            fields = decode(bytes.fromhex(record["packet"]))
            self.assertEqual((fields[2], fields[4], fields[5]), (status, 0x7FFF, 0x7FFF))

    def test_failure_is_reported_and_next_frame_works(self):
        def broken(*_):
            raise ValueError("test failure")
        working, self.processor.detector = self.processor.detector, broken
        self.assertEqual(self.processor.process(self.frame())["status"], "ERROR")
        self.processor.detector = working
        self.assertEqual(self.processor.process(self.frame())["status"], "FOUND")

    def test_late_processing_is_not_reported_as_found(self):
        frame = Frame(scene(), 0, time.monotonic_ns() - 300_000_000)
        self.assertEqual(self.processor.process(frame)["status"], "NO_FRAME")

    def test_smoothing_rate_side_and_lost_time(self):
        start = time.monotonic_ns()
        records = []
        for i, offset in enumerate((0.0, 0.1, 0.2, 0.3, 0.4)):
            frame = Frame(scene(offset), i, start + i * 33_000_000)
            records.append(self.processor.process(frame))
        last = records[-1]
        self.assertTrue(0.2 < last["smooth_offset"] < 0.4)   # Lags the raw 0.4.
        self.assertGreater(last["offset_rate"], 1.0)          # Moving right about 3/s.
        self.assertEqual((last["last_side"], last["lost_ms"]), (1, 0))
        lost = self.processor.process(Frame(scene(draw_line=False), 9, time.monotonic_ns()))
        fields = decode(bytes.fromhex(lost["packet"]))
        self.assertEqual((fields[2], fields[11]), (LineStatus.NO_LINE, 1))
        self.assertGreaterEqual(fields[12], 0)
        self.assertNotEqual(fields[6], 0x7FFF)  # Smoothed value kept briefly after losing it.

    def test_nothing_seen_yet(self):
        fields = decode(bytes.fromhex(self.processor.no_frame()["packet"]))
        self.assertEqual((fields[6], fields[7], fields[8], fields[12]), (0x7FFF, 0x7FFF, 0x7FFF, 0xFFFF))

    def test_sequence_increases(self):
        first, second = (decode(bytes.fromhex(self.processor.no_frame()["packet"]))[3] for _ in range(2))
        self.assertEqual((first, second), (0, 1))


if __name__ == "__main__":
    unittest.main()
