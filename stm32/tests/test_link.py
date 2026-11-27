"""STM32 link: send each packet once, add the waiting time to its ages, drop bad or old ones."""

import json
import os
import struct
import tempfile
import time
import unittest
from pathlib import Path

from link import PacketPicker, add_delay, crc16_ccitt_false, is_valid, sequence_of


def with_crc(body: bytes) -> bytes:
    return body + struct.pack("<H", crc16_ccitt_false(body))


def line_packet(sequence: int, age_ms: int = 40) -> bytes:
    return with_crc(b"\xC3\x4C" + struct.pack("<BBHhhhhhBBbHH", 2, 0, sequence, -120, 350, -100, 300,
                                              0, 90, 1, -1, 0, age_ms))


def fire_packet(sequence: int, seen_ms: int = 0xFFFF, age_ms: int = 300) -> bytes:
    return with_crc(b"\xC3\x6C" + struct.pack("<BBHhHHBBBBHH", 1, 1, sequence, 0x7FFF, 0xFFFF, 0xFFFF,
                                              0, 0, 5, 0, seen_ms, age_ms))


def summary_packet(sequence: int, age_ms: int = 150) -> bytes:
    return with_crc(b"\xC3\x5C" + struct.pack("<BBHHHHHhBH", 1, 0, sequence, 850, 0xFFFE, 300, 250,
                                              0, 0, age_ms))


def lidar_packet(sequence: int) -> bytes:
    zones = b"".join(struct.pack("<BHBH", 0, 1000 + i, 50, 0xFFFF if i == 3 else 120) for i in range(8))
    return with_crc(b"\xC3\x3C" + struct.pack("<BBHHHHHHHB", 3, 0, sequence, 50, 0, 5200, 192, 190,
                                              0xFFFF, 0xFF) + zones)


class PacketTest(unittest.TestCase):
    def test_add_delay_grows_ages_and_keeps_crc_valid(self):
        out = add_delay(line_packet(7, age_ms=40), 25)
        self.assertTrue(is_valid(out))
        self.assertEqual(struct.unpack_from("<H", out, 21)[0], 65)
        self.assertEqual(sequence_of(out), 7)

    def test_no_value_age_stays_no_value(self):
        out = add_delay(fire_packet(1, seen_ms=0xFFFF, age_ms=300), 50)
        self.assertEqual(struct.unpack_from("<H", out, 16)[0], 0xFFFF)  # Seen: no value.
        self.assertEqual(struct.unpack_from("<H", out, 18)[0], 350)

    def test_age_saturates_below_no_value(self):
        out = add_delay(summary_packet(1, age_ms=0xFFF0), 1000)
        self.assertEqual(struct.unpack_from("<H", out, 17)[0], 0xFFFE)

    def test_lidar_zone_ages(self):
        out = add_delay(lidar_packet(3), 10)
        ages = [struct.unpack_from("<H", out, 19 + 6 * i + 4)[0] for i in range(8)]
        self.assertEqual(ages, [130, 130, 130, 0xFFFF, 130, 130, 130, 130])
        self.assertTrue(is_valid(out))

    def test_rejects_bad_crc_and_unknown_type(self):
        bad = bytearray(line_packet(1))
        bad[6] ^= 1
        self.assertFalse(is_valid(bytes(bad)))
        self.assertFalse(is_valid(b"\xC3\x99" + bytes(20)))
        self.assertFalse(is_valid(b""))


class PickerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.picker = PacketPicker(self.folder, {"line": ["packet"], "lidar": ["summary_packet", "packet"],
                                                 "fire": ["packet"]}, max_delay_ms=300)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, value, age_s=0.0):
        path = self.folder / f"{name}.json"
        path.write_text(json.dumps({"captured_ns": 0, "value": value}))
        written = time.time_ns() - round(age_s * 1e9)
        os.utime(path, ns=(written, written))

    def test_each_packet_sent_once(self):
        self.write("line", {"packet": line_packet(1).hex()})
        self.assertEqual(len(self.picker.poll()), 1)
        self.assertEqual(self.picker.poll(), [])                        # File unchanged.
        self.write("line", {"packet": line_packet(1).hex()})           # Rewritten, same sequence.
        self.assertEqual(self.picker.poll(), [])
        self.write("line", {"packet": line_packet(2).hex()})
        self.assertEqual([sequence_of(p) for p in self.picker.poll()], [2])

    def test_same_sequence_in_different_sources_is_not_a_duplicate(self):
        self.write("line", {"packet": line_packet(5).hex()})
        self.write("fire", {"packet": fire_packet(5).hex()})
        self.write("lidar", {"packet": lidar_packet(5).hex(), "summary_packet": summary_packet(5).hex()})
        self.assertEqual(sorted(p[1] for p in self.picker.poll()), [0x3C, 0x4C, 0x5C, 0x6C])

    def test_waiting_time_added(self):
        self.write("line", {"packet": line_packet(1, age_ms=40).hex()}, age_s=0.1)
        (packet,) = self.picker.poll()
        self.assertGreaterEqual(struct.unpack_from("<H", packet, 21)[0], 140)

    def test_old_packet_dropped(self):
        self.write("line", {"packet": line_packet(1).hex()}, age_s=1.0)
        self.assertEqual(self.picker.poll(), [])
        self.assertEqual(self.picker.stats.stale, 1)

    def test_bad_files_counted_not_sent(self):
        (self.folder / "line.json").write_text("{half")
        self.write("fire", {"packet": "zz"})
        self.write("lidar", {"packet": "c34c00"})
        self.assertEqual(self.picker.poll(), [])
        self.assertEqual((self.picker.stats.unreadable, self.picker.stats.invalid), (1, 2))

    def test_missing_files_are_fine(self):
        self.assertEqual(self.picker.poll(), [])


if __name__ == "__main__":
    unittest.main()
