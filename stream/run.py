"""Stream process: shared camera frame -> JPEG -> web app server over WebSocket.

Never opens the camera. When the network or server is slow, old frames are skipped and
only the newest one is sent. When the server is down it keeps reconnecting.
Protocol: docs/stream.md
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
import tomllib
from pathlib import Path

import cv2

from common.framebus import read_frame

CONFIG_PATH = Path(__file__).with_name("config.toml")
NO_FRAME_REPORT_S = 2.0  # Repeat "camera has no frame" this often while it lasts.
IDLE_S = 0.01            # Wait between checks for a new frame.
LOG_EVERY_S = 60.0       # While the server stays down, repeat the warning this often.
WRITE_LIMIT = 64 * 1024  # Small send buffer: a slow link blocks send() instead of queueing old frames.


def load_config(path: Path = CONFIG_PATH) -> dict:
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    if not config["server_url"].startswith(("ws://", "wss://")):
        raise ValueError("server_url must start with ws:// or wss://")
    for key in ("width", "fps", "max_frame_age_s", "reconnect_min_s", "reconnect_max_s",
                "send_timeout_s"):
        if config[key] <= 0:
            raise ValueError(f"{key} must be positive")
    if not 1 <= config["jpeg_quality"] <= 100:
        raise ValueError("jpeg_quality must be 1..100")
    if config["reconnect_max_s"] < config["reconnect_min_s"]:
        raise ValueError("reconnect_max_s must be >= reconnect_min_s")
    return config


def encode_jpeg(image, width: int, quality: int) -> bytes:
    """Shrink to at most `width` pixels wide (keeping the shape) and encode as JPEG."""
    height, original_width = image.shape[:2]
    if original_width > width:
        image = cv2.resize(image, (width, round(height * width / original_width)),
                           interpolation=cv2.INTER_AREA)
    ok, data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("JPEG encoding failed")
    return data.tobytes()


def status_message(camera_ok: bool) -> str:
    return json.dumps({"type": "status", "camera": "ok" if camera_ok else "no_frame"})


def hello_message(config: dict) -> str:
    return json.dumps({"type": "hello", "car_id": config["car_id"], "format": "jpeg",
                       "max_width": config["width"], "fps": config["fps"]})


async def send_frames(websocket, config: dict, should_stop, read=read_frame) -> int:
    """Send the newest frame at most `fps` times a second until stopped. Return frames sent.

    Network errors and send timeouts propagate so the caller reconnects.
    """
    period = 1.0 / config["fps"]
    timeout = config["send_timeout_s"]
    await asyncio.wait_for(websocket.send(hello_message(config)), timeout)
    last_ns, sent = None, 0
    camera_ok, reported_at = None, 0.0
    next_at = time.monotonic()
    while not should_stop():
        now = time.monotonic()
        if now < next_at:
            await asyncio.sleep(next_at - now)
            continue
        frame = read(config["max_frame_age_s"], after_ns=last_ns)
        if frame is None:
            # Either the frame already sent is still the newest (camera between frames),
            # or there is no fresh frame at all. A newer fresh frame would have been returned.
            fresh = (last_ns is not None
                     and (time.monotonic_ns() - last_ns) / 1e9 <= config["max_frame_age_s"])
            if not fresh and (camera_ok is not False or now - reported_at >= NO_FRAME_REPORT_S):
                await asyncio.wait_for(websocket.send(status_message(False)), timeout)
                camera_ok, reported_at = False, now
            await asyncio.sleep(IDLE_S)
            continue
        if camera_ok is not True:
            await asyncio.wait_for(websocket.send(status_message(True)), timeout)
            camera_ok = True
        data = encode_jpeg(frame.image, config["width"], config["jpeg_quality"])
        await asyncio.wait_for(websocket.send(data), timeout)
        last_ns, sent = frame.captured_ns, sent + 1
        # Do not catch up on missed slots: after a slow send, just continue from now.
        next_at = max(next_at + period, time.monotonic())
    return sent


def connect(config: dict):
    from websockets.asyncio.client import connect as ws_connect  # Imported here so tests need no network.
    headers = {"Authorization": f"Bearer {config['token']}"} if config["token"] else None
    return ws_connect(config["server_url"], additional_headers=headers, open_timeout=5,
                      write_limit=WRITE_LIMIT, max_queue=4, compression=None)


async def run(config: dict, should_stop, connect=connect, send=send_frames, log=print) -> None:
    """Keep a connection to the server and stream; back off between failed attempts."""
    delay, failures, logged_at = config["reconnect_min_s"], 0, 0.0
    while not should_stop():
        started = time.monotonic()
        try:
            async with connect(config) as websocket:
                log(f"connected to {config['server_url']}")
                sent = await send(websocket, config, should_stop)
                log(f"stopped after {sent} frames")
                return
        except (OSError, asyncio.TimeoutError, ConnectionError) as error:
            reason = f"{type(error).__name__}: {error}"
        except Exception as error:  # websockets raises its own errors (InvalidURI, ConnectionClosed, ...).
            if type(error).__module__.split(".")[0] != "websockets":
                raise
            reason = f"{type(error).__name__}: {error}"
        if time.monotonic() - started > 10:
            delay, failures = config["reconnect_min_s"], 0  # It worked for a while; retry quickly.
        failures += 1
        # Log the first failures, then about once a minute: a missing server must not flood the journal.
        if failures <= 3 or time.monotonic() - logged_at >= LOG_EVERY_S:
            log(f"server unavailable ({reason}); retry in {delay:.0f}s (attempt {failures})")
            logged_at = time.monotonic()
        end = time.monotonic() + delay
        while time.monotonic() < end and not should_stop():
            await asyncio.sleep(0.1)
        delay = min(delay * 2, config["reconnect_max_s"])


def main() -> int:
    config = load_config()
    os.nice(10)  # Lowest priority area: line and LiDAR come first.
    cv2.setNumThreads(1)
    stopping = False

    def request_stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    asyncio.run(run(config, lambda: stopping,
                    log=lambda text: print(f"[stream] {text}", file=sys.stderr)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
