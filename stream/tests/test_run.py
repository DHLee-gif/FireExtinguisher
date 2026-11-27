import asyncio
import json
import time
import unittest
from pathlib import Path

import cv2
import numpy as np

from common.framebus import Frame
from run import encode_jpeg, load_config, run, send_frames

CONFIG = load_config(Path(__file__).resolve().parents[1] / "config.toml")


def config(**changes):
    return {**CONFIG, **changes}


class FakeSocket:
    def __init__(self, fail_after=None, delay_s=0.0):
        self.messages, self.fail_after, self.delay_s = [], fail_after, delay_s

    async def send(self, message):
        if self.fail_after is not None and len(self.messages) >= self.fail_after:
            raise ConnectionResetError("link lost")
        await asyncio.sleep(self.delay_s)
        self.messages.append(message)

    def frames(self):
        return [m for m in self.messages if isinstance(m, bytes)]

    def texts(self):
        return [json.loads(m) for m in self.messages if isinstance(m, str)]


class Camera:
    """Fake shared frame: a new frame every `period_s`, or none at all."""

    def __init__(self, period_s=1 / 30, alive=True):
        self.period_s, self.alive, self.started = period_s, alive, time.monotonic_ns()

    def __call__(self, max_age_s, after_ns=None):
        if not self.alive:
            return None
        index = int((time.monotonic_ns() - self.started) / 1e9 / self.period_s)
        captured = self.started + int(index * self.period_s * 1e9)
        if captured == after_ns:
            return None
        image = np.full((480, 640, 3), index % 255, np.uint8)
        return Frame(image, index, captured)


def stop_after(seconds):
    end = time.monotonic() + seconds
    return lambda: time.monotonic() >= end


class EncodeTest(unittest.TestCase):
    def test_shrinks_and_keeps_shape(self):
        image = np.zeros((480, 640, 3), np.uint8)
        decoded = cv2.imdecode(np.frombuffer(encode_jpeg(image, 320, 70), np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape, (240, 320, 3))

    def test_never_enlarges(self):
        image = np.zeros((480, 640, 3), np.uint8)
        decoded = cv2.imdecode(np.frombuffer(encode_jpeg(image, 1920, 70), np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape, (480, 640, 3))


class SendTest(unittest.TestCase):
    def test_hello_then_camera_ok_then_frames_at_fps(self):
        socket = FakeSocket()
        sent = asyncio.run(send_frames(socket, config(fps=10), stop_after(1.0), Camera()))
        texts = socket.texts()
        self.assertEqual(texts[0]["type"], "hello")
        self.assertEqual(texts[1], {"type": "status", "camera": "ok"})
        self.assertEqual(sent, len(socket.frames()))
        self.assertTrue(8 <= sent <= 11, sent)  # 10 fps for 1 s
        self.assertEqual(socket.frames()[0][:2], b"\xff\xd8")  # JPEG

    def test_never_sends_the_same_frame_twice(self):
        socket = FakeSocket()
        # Camera slower (5 fps) than the stream (15 fps): only new frames go out.
        sent = asyncio.run(send_frames(socket, config(fps=15), stop_after(1.0), Camera(period_s=0.2)))
        self.assertTrue(4 <= sent <= 6, sent)

    def test_dead_camera_is_reported_not_silent(self):
        socket = FakeSocket()
        sent = asyncio.run(send_frames(socket, config(), stop_after(0.3), Camera(alive=False)))
        self.assertEqual(sent, 0)
        self.assertIn({"type": "status", "camera": "no_frame"}, socket.texts())

    def test_slow_link_skips_old_frames(self):
        socket = FakeSocket(delay_s=0.25)  # Each send takes 0.25 s; no backlog may build up.
        start = time.monotonic()
        asyncio.run(send_frames(socket, config(fps=30), stop_after(1.0), Camera()))
        self.assertLess(time.monotonic() - start, 1.6)
        self.assertLessEqual(len(socket.frames()), 5)

    def test_network_error_reaches_caller(self):
        with self.assertRaises(ConnectionResetError):
            asyncio.run(send_frames(FakeSocket(fail_after=3), config(), stop_after(2.0), Camera()))


class ReconnectTest(unittest.TestCase):
    def test_keeps_retrying_while_server_is_down(self):
        attempts, logs = [], []

        class Refused:
            async def __aenter__(self):
                attempts.append(time.monotonic())
                raise ConnectionRefusedError("refused")

            async def __aexit__(self, *_):
                return False

        asyncio.run(run(config(reconnect_min_s=0.1, reconnect_max_s=0.2), stop_after(0.7),
                        connect=lambda _: Refused(), log=logs.append))
        self.assertGreaterEqual(len(attempts), 4)
        self.assertTrue(all("retry" in line for line in logs))
        self.assertEqual(len(logs), 3)  # Then quiet for a minute: no journal flood.

    def test_bad_config_rejected(self):
        with self.assertRaises(ValueError):
            path = Path(self.id() + ".toml")
            try:
                path.write_text(Path(__file__).resolve().parents[1].joinpath("config.toml")
                                .read_text().replace('ws://127.0.0.1', 'http://127.0.0.1'))
                load_config(path)
            finally:
                path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
