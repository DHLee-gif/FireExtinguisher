import tempfile
import unittest
from pathlib import Path

import numpy as np

from capture import camera_controls, load_config, publish_loop
from common.framebus import read_frame


class CaptureTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def test_shipped_config_is_valid(self):
        self.assertGreater(load_config()["fps"], 0)

    def test_rejects_bad_config(self):
        bad = self.folder / "config.toml"
        bad.write_text("width=0\nheight=480\nfps=30\nexposure_us=0\ngain=1.0\nrotate_180=false\nstall_timeout_s=2.0\n")
        with self.assertRaises(ValueError):
            load_config(bad)

    def test_auto_and_fixed_exposure(self):
        self.assertNotIn("AeEnable", camera_controls({"fps": 30, "exposure_us": 0, "gain": 1.0}))
        fixed = camera_controls({"fps": 30, "exposure_us": 8000, "gain": 2.0})
        self.assertEqual((fixed["AeEnable"], fixed["ExposureTime"], fixed["AnalogueGain"]),
                         (False, 8000, 2.0))

    def test_publishes_latest_frame(self):
        path = self.folder / "bus" / "frame.bin"
        values = iter(range(3))
        stops = iter([False, False, False, True])
        count = publish_loop(lambda: np.full((2, 2, 3), next(values), np.uint8),
                             lambda: next(stops), path)
        frame = read_frame(1.0, path)
        self.assertEqual((count, frame.sequence, int(frame.image[0, 0, 0])), (3, 2, 2))

    def test_camera_error_is_not_hidden(self):
        def stalled():
            raise TimeoutError
        with self.assertRaises(TimeoutError):
            publish_loop(stalled, lambda: False, self.folder / "frame.bin")


if __name__ == "__main__":
    unittest.main()
