import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from common.framebus import read_frame, write_frame


class FrameBusTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "frame.bin"
        self.image = np.arange(4 * 6 * 3, dtype=np.uint8).reshape(4, 6, 3)

    def test_round_trip(self):
        write_frame(self.image, 7, time.monotonic_ns(), self.path)
        frame = read_frame(1.0, self.path)
        np.testing.assert_array_equal(frame.image, self.image)
        self.assertEqual(frame.sequence, 7)

    def test_missing_is_none(self):
        self.assertIsNone(read_frame(1.0, self.path))

    def test_old_and_future_frames_are_none(self):
        for offset in (-2_000_000_000, 60_000_000_000):
            write_frame(self.image, 0, time.monotonic_ns() + offset, self.path)
            self.assertIsNone(read_frame(1.0, self.path))

    def test_damaged_is_none(self):
        write_frame(self.image, 0, time.monotonic_ns(), self.path)
        good = self.path.read_bytes()
        for bad in (b"", good[:10], good[:-1], b"XXXX" + good[4:]):
            self.path.write_bytes(bad)
            self.assertIsNone(read_frame(1.0, self.path))

    def test_reader_keeps_its_frame_after_replacement(self):
        write_frame(self.image, 0, time.monotonic_ns(), self.path)
        first = read_frame(1.0, self.path)
        write_frame(np.zeros_like(self.image), 1, time.monotonic_ns(), self.path)
        np.testing.assert_array_equal(first.image, self.image)

    def test_after_ns_skips_a_frame_already_seen(self):
        write_frame(self.image, 0, time.monotonic_ns(), self.path)
        seen = read_frame(1.0, self.path).captured_ns
        self.assertIsNone(read_frame(1.0, self.path, after_ns=seen))
        write_frame(self.image, 1, time.monotonic_ns(), self.path)
        self.assertEqual(read_frame(1.0, self.path, after_ns=seen).sequence, 1)

    def test_rejects_wrong_shape(self):
        with self.assertRaises(ValueError):
            write_frame(np.zeros((4, 6), np.uint8), 0, 0, self.path)


if __name__ == "__main__":
    unittest.main()
