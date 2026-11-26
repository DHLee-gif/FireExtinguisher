import tempfile
import time
import unittest
from pathlib import Path

from common.valuebus import read_value, write_value


class ValueBusTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def test_round_trip(self):
        write_value("line", {"a": 1}, time.monotonic_ns(), self.folder)
        self.assertEqual(read_value("line", 1.0, self.folder), {"a": 1})

    def test_missing_old_future_damaged_are_none(self):
        self.assertIsNone(read_value("line", 1.0, self.folder))
        for offset in (-2_000_000_000, 60_000_000_000):
            write_value("line", {}, time.monotonic_ns() + offset, self.folder)
            self.assertIsNone(read_value("line", 1.0, self.folder))
        for text in ("", "{", "[]", "{}", '{"captured_ns": "x", "value": {}}'):
            (self.folder / "line.json").write_text(text)
            self.assertIsNone(read_value("line", 1.0, self.folder))


if __name__ == "__main__":
    unittest.main()
