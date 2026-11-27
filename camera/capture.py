"""Camera process: the only owner of the camera. Publishes the latest frame."""

from __future__ import annotations

import signal
import sys
import time
import tomllib
from pathlib import Path

from common.framebus import DEFAULT_PATH, write_frame

CONFIG_PATH = Path(__file__).with_name("config.toml")


def load_config(path: Path = CONFIG_PATH) -> dict:
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    for key in ("width", "height", "fps", "stall_timeout_s"):
        if config[key] <= 0:
            raise ValueError(f"{key} must be positive")
    if not isinstance(config["rotate_180"], bool):
        raise ValueError("rotate_180 must be true or false")
    if config["exposure_us"] < 0 or config["gain"] < 1.0:
        raise ValueError("exposure_us must be >= 0 and gain >= 1.0")
    return config


def camera_controls(config: dict) -> dict:
    controls = {"FrameRate": config["fps"]}
    if config["exposure_us"]:
        controls.update(AeEnable=False, ExposureTime=config["exposure_us"],
                        AnalogueGain=config["gain"])
    return controls


def publish_loop(capture, should_stop, path: Path = DEFAULT_PATH) -> int:
    """Publish frames until asked to stop. Camera errors propagate to the caller."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sequence = 0
    while not should_stop():
        image = capture()
        write_frame(image, sequence, time.monotonic_ns(), path)
        sequence += 1
    return sequence


def main() -> int:
    from libcamera import Transform  # Imported here so tests need no camera.
    from picamera2 import Picamera2

    config = load_config()
    stopping = False

    def request_stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    camera = Picamera2()
    try:
        # picamera2 "RGB888" is B, G, R in memory, which is what OpenCV expects.
        camera.configure(camera.create_video_configuration(
            main={"size": (config["width"], config["height"]), "format": "RGB888"},
            controls=camera_controls(config),
            transform=Transform(hflip=config["rotate_180"], vflip=config["rotate_180"])))
        camera.start()
        started = time.monotonic()

        def capture():
            request = camera.capture_request(wait=config["stall_timeout_s"])
            try:
                return request.make_array("main")
            finally:
                request.release()

        count = publish_loop(capture, lambda: stopping)
        print(f"stopped: {count} frames, {count / (time.monotonic() - started):.1f} fps",
              file=sys.stderr)
        return 0
    except TimeoutError:
        print(f"camera stalled for {config['stall_timeout_s']}s", file=sys.stderr)
        return 1
    finally:
        camera.close()


if __name__ == "__main__":
    sys.exit(main())
