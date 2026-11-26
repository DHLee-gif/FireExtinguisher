import struct
import time
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import serial

from lidar_bridge import (
    CycleStatus,
    FrameStream,
    MeasurementStatus,
    ScanCycle,
    crc16_ccitt_false,
    encode_cycle,
    is_complete,
    open_serial_with_retry,
    run,
)
from lidar_data_processor import SCAN_FRAME_SIZE, calc_camsense_checksum


def make_frame(start_deg, end_deg, samples, speed_hz=5.2):
    frame = bytearray(SCAN_FRAME_SIZE)
    frame[:4] = b"\x55\xaa\x03\x08"
    frame[4:6] = round(speed_hz * 3840).to_bytes(2, "little")
    frame[6:8] = round((start_deg + 640) * 64).to_bytes(2, "little")
    for index, (raw_distance, quality) in enumerate(samples):
        offset = 8 + index * 3
        frame[offset:offset + 2] = raw_distance.to_bytes(2, "little")
        frame[offset + 2] = quality
    frame[32:34] = round((end_deg + 640) * 64).to_bytes(2, "little")
    frame[34:36] = calc_camsense_checksum(frame).to_bytes(2, "little")
    return bytes(frame)


class LidarBridgeTests(unittest.TestCase):
    def test_serial_open_retries_transient_failure(self):
        device = object()
        with patch("lidar_bridge.serial.Serial", side_effect=[
            serial.SerialException("not ready"), device
        ]) as serial_open, patch("lidar_bridge.time.sleep") as sleep:
            self.assertIs(open_serial_with_retry("/dev/ttyTEST", 115200, "test"), device)

        self.assertEqual(serial_open.call_count, 2)
        sleep.assert_called_once_with(1.0)

    def test_frame_stream_resynchronizes_after_checksum_error(self):
        samples = [(500, 7)] * 8
        good = make_frame(0, 7, samples)
        bad = bytearray(good)
        bad[12] ^= 1

        decoded = list(FrameStream().feed(bytes(bad) + good))

        self.assertEqual(decoded, [None, good])

    def test_classifies_too_close_and_no_return_separately(self):
        samples = [(0, 0)] * 8
        samples[0] = (80, 42)
        cycle = ScanCycle(0)
        cycle.add_frame(make_frame(-2, 2, samples), 28.5, 120, 8000)

        front = cycle.zones[0]
        self.assertEqual(front.status, MeasurementStatus.TOO_CLOSE)
        self.assertEqual(front.distance_mm, 80)
        self.assertEqual(front.quality, 42)
        no_return_cycle = ScanCycle(1)
        no_return_cycle.add_frame(make_frame(-2, 2, [(0, 0)] * 8), 28.5, 120, 8000)
        self.assertEqual(no_return_cycle.zones[0].status, MeasurementStatus.NO_RETURN)

    def test_classifies_sensor_invalid_and_too_far(self):
        invalid_cycle = ScanCycle(0)
        invalid_cycle.add_frame(
            make_frame(-2, 2, [(0x8000 | 500, 12)] * 8), 28.5, 120, 8000
        )
        far_cycle = ScanCycle(1)
        far_cycle.add_frame(make_frame(-2, 2, [(9000, 13)] * 8), 28.5, 120, 8000)

        self.assertEqual(invalid_cycle.zones[0].status, MeasurementStatus.SENSOR_INVALID)
        self.assertEqual(far_cycle.zones[0].status, MeasurementStatus.TOO_FAR)
        self.assertEqual(far_cycle.zones[0].distance_mm, 9000)

    def test_marks_cycles_incomplete_for_missing_coverage_or_bad_frames(self):
        cycle = ScanCycle(3)
        cycle.angular_coverage_deg = 355
        cycle.valid_frames = 48
        cycle.observed_zone_mask = 0xFF
        self.assertTrue(is_complete(cycle, 52))
        cycle.add_bad_frame()
        self.assertFalse(is_complete(cycle, 52))
        cycle.bad_frames = 0
        cycle.angular_coverage_deg = 340
        self.assertFalse(is_complete(cycle, 52))
        cycle.angular_coverage_deg = 355
        cycle.observed_zone_mask = 0x7F
        self.assertFalse(is_complete(cycle, 52))

    def test_emits_fixed_69_byte_packet_with_crc_and_scan_speed(self):
        cycle = ScanCycle(0)
        cycle.speed_hz = 5.2
        cycle.valid_frames = 52
        packet = encode_cycle(
            cycle,
            sequence=0x1234,
            cycle_status=CycleStatus.PARTIAL,
            max_unobserved_travel_mm=100,
        )

        self.assertEqual(len(packet), 69)
        self.assertEqual(packet[:4], b"\xC3\x3C\x03\x01")
        self.assertEqual(struct.unpack_from("<H", packet, 4)[0], 0x1234)
        self.assertEqual(struct.unpack_from("<H", packet, 10)[0], 5200)
        self.assertEqual(struct.unpack_from("<H", packet, 12)[0], 192)
        self.assertEqual(packet[18], 0)
        self.assertEqual(struct.unpack_from("<H", packet, 16)[0], 521)
        self.assertEqual(struct.unpack_from("<H", packet, 67)[0], crc16_ccitt_false(packet[:67]))

    def test_packet_contains_per_zone_measurement_age_and_no_data_sentinel(self):
        cycle = ScanCycle(0)
        cycle.add_frame(
            make_frame(-2, 2, [(500, 21)] * 8),
            forward_angle_deg=28.5,
            min_range_mm=120,
            max_range_mm=8000,
            measured_at=time.monotonic() - 0.25,
        )
        packet = encode_cycle(
            cycle,
            sequence=0,
            cycle_status=CycleStatus.PARTIAL,
            max_unobserved_travel_mm=0,
        )

        self.assertTrue(packet[18] & 0x01)
        front_record = 19
        self.assertGreaterEqual(struct.unpack_from("<H", packet, front_record + 4)[0], 350)
        self.assertEqual(struct.unpack_from("<H", packet, 25 + 4)[0], 0xFFFF)

    def test_cycle_elapsed_time_reduces_latency_speed_bound(self):
        cycle = ScanCycle(0)
        cycle.speed_hz = 5.2
        cycle.started_at = time.monotonic() - 1.5
        packet = encode_cycle(
            cycle,
            sequence=1,
            cycle_status=CycleStatus.PARTIAL,
            max_unobserved_travel_mm=100,
        )

        self.assertGreaterEqual(struct.unpack_from("<H", packet, 14)[0], 1500)
        self.assertEqual(struct.unpack_from("<H", packet, 16)[0], 67)

    def test_serial_open_stops_after_six_total_attempts(self):
        failures = [serial.SerialException("still unavailable") for _ in range(6)]
        with patch("lidar_bridge.serial.Serial", side_effect=failures) as serial_open, \
                patch("lidar_bridge.time.sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "after 6 attempts"):
                open_serial_with_retry("/dev/ttyTEST", 115200, "test")

        self.assertEqual(serial_open.call_count, 6)
        self.assertEqual(sleep.call_count, 5)

    def test_com5_capture_runs_through_bridge_to_stm32_packets(self):
        capture_path = Path(__file__).resolve().parents[1] / "captures" / "COM5_2026-11-16.hex"
        capture = bytes.fromhex(capture_path.read_text(encoding="ascii"))

        class CaptureInput:
            def __init__(self):
                self.offset = 0

            def read(self, size):
                if self.offset >= len(capture):
                    raise KeyboardInterrupt
                chunk = capture[self.offset:self.offset + size]
                self.offset += len(chunk)
                return chunk

            def close(self):
                pass

        class PacketOutput:
            def __init__(self):
                self.packets = []

            def write(self, packet):
                self.packets.append(packet)
                return len(packet)

            def close(self):
                pass

        source = CaptureInput()
        destination = PacketOutput()
        args = Namespace(
            lidar_port="capture",
            stm32_port="memory",
            lidar_baud=115200,
            stm32_baud=115200,
            forward_angle=0.0,
            min_range_mm=120,
            max_range_mm=8000,
            expected_frames=52,
            max_unobserved_travel_mm=0,
        )

        with patch("lidar_bridge.serial.Serial", side_effect=[destination, source]):
            run(args)

        self.assertGreaterEqual(len(destination.packets), 5)
        self.assertTrue(all(len(packet) == 69 for packet in destination.packets))
        self.assertEqual(destination.packets[0][3], CycleStatus.STARTUP_PARTIAL)
        self.assertEqual(
            [struct.unpack_from("<H", packet, 4)[0] for packet in destination.packets],
            list(range(len(destination.packets))),
        )
        self.assertTrue(all(
            struct.unpack_from("<H", packet, 67)[0] == crc16_ccitt_false(packet[:67])
            for packet in destination.packets
        ))


if __name__ == "__main__":
    unittest.main()
