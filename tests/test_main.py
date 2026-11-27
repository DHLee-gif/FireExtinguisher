"""main.py supervisor: a failing optional process must not stop the driving processes."""

import sys
import time
import unittest

import os
import tempfile
from pathlib import Path

from main import build_commands, load_cores, supervise

DIES = [sys.executable, "-c", "raise SystemExit(3)"]
LIVES = [sys.executable, "-c", "import time; time.sleep(30)"]


def stop_after(seconds):
    end = time.monotonic() + seconds
    return lambda: time.monotonic() >= end


class SuperviseTest(unittest.TestCase):
    def test_dying_optional_process_does_not_stop_others(self):
        result = supervise({"lidar": LIVES, "stream": DIES}, stop_after(1.5), restart_s=0.05,
                           max_deaths=3, window_s=60, optional={"stream"}, optional_backoff_s=10)
        self.assertEqual(result, 0)  # Stopped on request, not because stream kept dying.

    def test_dying_driving_process_stops_everything(self):
        start = time.monotonic()
        result = supervise({"lidar": DIES, "stream": LIVES}, stop_after(10), restart_s=0.05,
                           max_deaths=3, window_s=60, optional={"stream"})
        self.assertEqual(result, 1)
        self.assertLess(time.monotonic() - start, 5)

    def test_stream_can_be_left_out(self):
        self.assertIn("stream", build_commands())
        self.assertNotIn("stream", build_commands(stream=False))
        self.assertIn("fire", build_commands())
        self.assertNotIn("fire", build_commands(fire=False))
        self.assertIn("stm32", build_commands())
        self.assertNotIn("stm32", build_commands(stm32=False))

    def test_process_runs_only_on_its_cores(self):
        core = min(os.sched_getaffinity(0))
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "cores"
            report = [sys.executable, "-c",
                      f"import os, time; open({str(out)!r}, 'w').write(str(sorted(os.sched_getaffinity(0)))); time.sleep(30)"]
            supervise({"line": report}, stop_after(1.0), cores={"line": {core}})
            self.assertEqual(out.read_text(), str([core]))


class CoresTest(unittest.TestCase):
    def test_project_core_map_is_valid(self):
        cores = load_cores(names=build_commands().keys())
        self.assertEqual(set(cores), set(build_commands()))
        self.assertTrue(cores["line"].isdisjoint(cores["fire"] | cores["stream"]))

    def test_rejects_unknown_core(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "main.toml"
            path.write_text("[cores]\nline = [99]\n")
            with self.assertRaises(ValueError):
                load_cores(path)


if __name__ == "__main__":
    unittest.main()
