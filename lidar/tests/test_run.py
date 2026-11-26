import struct
import time
import unittest
from pathlib import Path

import serial

from lidar_bridge import FrameStream, crc16_ccitt_false
from run import CycleBuilder, load_config, step

CAPTURE = Path(__file__).parents[1] / "captures" / "COM5_2026-11-16.hex"


class RunTests(unittest.TestCase):
    def setUp(self):
        self.builder = CycleBuilder(load_config())
        self.data = bytes.fromhex(CAPTURE.read_text())

    def test_capture_gives_valid_packets_matching_the_values(self):
        records = self.builder.feed(self.data, time.monotonic())
        self.assertGreaterEqual(len(records), 5)
        self.assertEqual(records[0]["status"], "STARTUP_PARTIAL")
        self.assertIn("COMPLETE", [record["status"] for record in records])
        for index, record in enumerate(records):
            packet = bytes.fromhex(record["packet"])
            self.assertEqual((len(packet), packet[:3]), (69, b"\xC3\x3C\x03"))
            self.assertEqual(struct.unpack_from("<H", packet, 67)[0], crc16_ccitt_false(packet[:67]))
            self.assertEqual(struct.unpack_from("<H", packet, 4)[0], index)
            for i, zone in enumerate(record["zones"].values()):
                distance = struct.unpack_from("<H", packet, 20 + 6 * i)[0]
                self.assertEqual(distance, 0xFFFF if zone["distance_mm"] is None else zone["distance_mm"])

    def test_chunk_size_does_not_change_values(self):
        whole = self.builder.feed(self.data, time.monotonic())
        other, pieces = CycleBuilder(load_config()), []
        for i in range(0, len(self.data), 7):
            pieces += other.feed(self.data[i:i + 7], time.monotonic())

        def without_age(records):
            return [{name: {k: v for k, v in zone.items() if k != "age_ms"}
                     for name, zone in r["zones"].items()} for r in records]

        self.assertEqual(without_age(whole), without_age(pieces))

    def test_corruption_is_counted_not_used(self):
        damaged = bytearray(self.data)
        damaged[3000] ^= 0xFF
        records = self.builder.feed(bytes(damaged), time.monotonic())
        self.assertGreater(sum(r["bad_frames"] for r in records), 0)

    def frames(self):
        return [f for f in FrameStream().feed(self.data) if f]

    def statuses(self, frames):
        builder = CycleBuilder(load_config())
        return [r["status"] for r in builder.feed(b"".join(frames), time.monotonic())]

    def test_every_lost_frame_prevents_complete(self):
        frames = self.frames()
        self.assertEqual(self.statuses(frames)[1:], ["COMPLETE"] * 6)
        for count in (1, 2, 3, 20, 26, 28, 30, 45):
            for first in range(60, 160, 9):
                with self.subTest(count=count, first=first):
                    got = self.statuses(frames[:first] + frames[first + count:])
                    self.assertLess(got.count("COMPLETE"), 6)
                    self.assertIn("PARTIAL", got)

    def test_damaged_header_prevents_complete(self):
        frames = self.frames()
        for byte in range(4):
            damaged = bytearray(frames[80])
            damaged[byte] ^= 0xFF
            self.assertIn("PARTIAL", self.statuses(frames[:80] + [bytes(damaged)] + frames[81:]))

    def test_whole_lost_revolution_is_detected_by_time(self):
        frames = self.frames()
        records = self.builder.feed(b"".join(frames[:60]), time.monotonic())
        self.builder.cycle.started_at -= 0.35
        records = self.builder.feed(b"".join(frames[60:110]), time.monotonic())
        self.assertEqual(records[0]["status"], "PARTIAL")

    def test_backlog_is_dropped(self):
        class Behind:
            in_waiting = 4000
            def reset_input_buffer(self):
                self.in_waiting = 0
            def read(self, _):
                return b""
        device = Behind()
        self.builder.feed(b"".join(self.frames()[:60]), time.monotonic())
        step(None, device, self.builder)
        self.assertEqual((device.in_waiting, self.builder.cycle.valid_frames), (0, 0))

    def test_captured_time_is_the_oldest_measurement(self):
        measured = time.monotonic() - 0.3
        record = self.builder.feed(self.data, measured)[1]
        self.assertAlmostEqual(record["captured_ns"] / 1e9, measured, delta=0.001)
        self.assertGreaterEqual(record["zones"]["front"]["age_ms"], 300)

    def test_silence_reports_no_data(self):
        self.builder.cycle.started_at -= 1.0
        record, = self.builder.feed(b"", time.monotonic())
        self.assertEqual(record["status"], "PARTIAL")
        self.assertEqual({z["status"] for z in record["zones"].values()}, {"NO_DATA"})

    def test_missing_sensor_then_reconnect(self):
        def missing():
            raise serial.SerialException("test: not plugged in")

        class Unplugged:
            in_waiting = 0
            def read(self, _):
                raise OSError("test: unplugged")
            def close(self):
                self.closed = True

        class Working:
            in_waiting = 0
            def read(_, __):
                return self.data

        source, records = step(missing, None, self.builder)
        self.assertIsNone(source)
        self.assertEqual({z["status"] for z in records[0]["zones"].values()}, {"NO_DATA"})
        device = Unplugged()
        self.assertIsNone(step(missing, device, self.builder)[0])
        self.assertTrue(device.closed)
        source, records = step(Working, None, self.builder)
        self.assertIsNotNone(source)
        self.assertTrue(records)


if __name__ == "__main__":
    unittest.main()
