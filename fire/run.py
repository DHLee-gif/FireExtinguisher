"""Fire process: shared frame -> YOLO -> shared "fire" value with a ready-to-send packet.

"No fire" (looked, nothing there) and "no fire value" (no model / no frame / error) are
different statuses. Fire counts only when seen in several recent frames. Packet: docs/fire.md
"""

from __future__ import annotations

import os
import signal
import sys
import time
from collections import deque
from dataclasses import asdict

import cv2

from common.framebus import read_frame
from common.valuebus import write_value
from detector import Detection, detect, load_config, load_model, model_file
from packet import FireStatus, encode

MODEL_RETRY_S = 5.0
REPORT_S = 0.5  # How often to repeat an "unknown" status while it lasts.


class FireProcessor:
    def __init__(self, config: dict):
        self.config = config
        self.history = deque(maxlen=config["window"])  # True = fire seen in that frame.
        self.confirmed = False
        self.target: Detection | None = None
        self.seen_ns: int | None = None
        self.sequence = 0

    def _record(self, status: FireStatus, age_s: float | None, detections=(), now_ns=None) -> dict:
        now_ns = time.monotonic_ns() if now_ns is None else now_ns
        hits = sum(self.history)
        seen_s = None if self.seen_ns is None else (now_ns - self.seen_ns) / 1e9
        target = self.target if status in (FireStatus.FIRE, FireStatus.SUSPECT) else None
        packet = encode(status, self.sequence, target, seen_s if target else None, hits,
                        self.config["window"], len(detections), age_s)
        self.sequence = (self.sequence + 1) & 0xFFFF
        known = status in (FireStatus.FIRE, FireStatus.NO_FIRE, FireStatus.SUSPECT)
        return {
            "status": status.name,
            "fire": (status == FireStatus.FIRE) if known else None,  # None = no fire value.
            "hits": hits, "window": self.config["window"],
            "target": asdict(target) if target else None,
            "seen_ms": round(seen_s * 1000) if target and seen_s is not None else None,
            "detections": [asdict(d) for d in detections[:5]],
            "packet": packet.hex(),
        }

    def process(self, detections: list[Detection], captured_ns: int, age_s: float,
                now_ns: int | None = None) -> dict:
        seen = bool(detections)
        self.history.append(seen)
        if seen:
            self.target, self.seen_ns = detections[0], captured_ns
        hits = sum(self.history)
        if self.confirmed:
            self.confirmed = hits >= 1  # Stay confirmed until a whole window has no fire.
        else:
            self.confirmed = hits >= self.config["confirm_hits"]
        if hits == 0:
            self.target, self.seen_ns = None, None
        status = FireStatus.FIRE if self.confirmed else FireStatus.SUSPECT if hits else FireStatus.NO_FIRE
        return self._record(status, age_s, detections, now_ns)

    def unknown(self, status: FireStatus, age_s: float | None = None) -> dict:
        """No fire value this time. Confirmation starts over once values come back."""
        self.history.clear()
        self.confirmed, self.target, self.seen_ns = False, None, None
        return self._record(status, age_s)


def main() -> int:
    config = load_config()
    os.nice(5)  # Below line and LiDAR, above streaming.
    cv2.setNumThreads(config["threads"])
    stopping = False

    def request_stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    processor = FireProcessor(config)
    path = model_file(config)
    net, next_load, missing_logged = None, 0.0, False
    last_ns, last_report, next_at, count = None, 0.0, 0.0, 0
    started = time.monotonic()
    while not stopping:
        now = time.monotonic()
        if net is None:
            if now >= next_load:
                next_load = now + MODEL_RETRY_S
                try:
                    net = load_model(path)
                    print(f"model loaded: {path}", file=sys.stderr)
                except FileNotFoundError:
                    if not missing_logged:
                        print(f"no model at {path}; reporting NO_MODEL (see docs/fire.md)", file=sys.stderr)
                        missing_logged = True
                except cv2.error as error:
                    print(f"cannot load model {path}: {error}", file=sys.stderr)
            if net is None:
                if now - last_report >= REPORT_S:
                    write_value("fire", processor.unknown(FireStatus.NO_MODEL), time.monotonic_ns())
                    last_report = now
                time.sleep(0.1)
                continue
        if now < next_at:
            time.sleep(min(0.01, next_at - now))
            continue
        frame = read_frame(config["max_frame_age_s"], after_ns=last_ns)
        if frame is None:
            stale = last_ns is None or (time.monotonic_ns() - last_ns) / 1e9 > config["max_frame_age_s"]
            if stale and now - last_report >= REPORT_S:
                write_value("fire", processor.unknown(FireStatus.NO_FRAME), time.monotonic_ns())
                last_report = now
            time.sleep(0.005)
            continue
        # Next slot one period after this frame: never two frames back to back after a pause,
        # which would confirm fire faster than `window`/`max_fps` intends.
        next_at = max(next_at, now) + 1 / config["max_fps"]
        last_ns, last_report = frame.captured_ns, now
        try:
            detections = detect(net, frame.image, config)
        except (cv2.error, ValueError) as error:  # Reported as ERROR, never as "no fire".
            print(f"fire detection failed: {type(error).__name__}: {error}", file=sys.stderr)
            write_value("fire", processor.unknown(FireStatus.ERROR, frame.age_s()), frame.captured_ns)
            continue
        if frame.age_s() > config["max_frame_age_s"]:  # Processed too late to count.
            write_value("fire", processor.unknown(FireStatus.NO_FRAME, frame.age_s()), frame.captured_ns)
            continue
        write_value("fire", processor.process(detections, frame.captured_ns, frame.age_s()),
                    frame.captured_ns)
        count += 1
    print(f"stopped: {count} frames, {count / (time.monotonic() - started):.1f} fps", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
