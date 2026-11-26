"""Line process: shared frame -> shared "line" value with a ready-to-send packet."""

from __future__ import annotations

import signal
import sys
import time
from dataclasses import asdict

import cv2

from common.framebus import read_frame
from common.valuebus import write_value
from detector import detect, load_config
from packet import LineStatus, encode

MEMORY_S = 0.5  # How long a lost line's position still decides which line to follow.
SIDE_DEADBAND = 0.1  # |offset| below this counts as centered for last_side.
IDLE_REPORT_S = 0.1


class LineProcessor:
    def __init__(self, config, detector=detect):
        self.config, self.detector = config, detector
        self.sequence = 0
        self.previous_offset, self.seen_at = None, None
        self.smooth = None  # (offset, angle, captured seconds)
        self.rate = None
        self.last_side = 0

    def _track(self, result, captured_s):
        """Smooth found values, estimate how fast the offset changes, remember where it went."""
        alpha = self.config["smoothing"]
        if result is not None and result.found:
            if self.smooth is None or captured_s - self.smooth[2] > MEMORY_S:
                self.smooth, self.rate = (result.offset, result.angle_deg, captured_s), None
            else:
                offset = self.smooth[0] + alpha * (result.offset - self.smooth[0])
                angle = self.smooth[1] + alpha * (result.angle_deg - self.smooth[1])
                elapsed = captured_s - self.smooth[2]
                if elapsed > 0:
                    rate = (offset - self.smooth[0]) / elapsed
                    self.rate = rate if self.rate is None else self.rate + alpha * (rate - self.rate)
                self.smooth = (offset, angle, captured_s)
            if abs(result.offset) >= SIDE_DEADBAND:
                self.last_side = 1 if result.offset > 0 else -1
            else:
                self.last_side = 0
        recent = self.smooth is not None and time.monotonic() - self.smooth[2] <= MEMORY_S
        lost_ms = None if self.seen_at is None else max(0, round((time.monotonic() - self.seen_at) * 1000))
        return {
            "smooth_offset": round(self.smooth[0], 4) if recent else None,
            "smooth_angle_deg": round(self.smooth[1], 2) if recent else None,
            "offset_rate": round(self.rate, 3) if recent and self.rate is not None else None,
            "last_side": self.last_side,
            "lost_ms": 0 if result is not None and result.found else lost_ms,
        }

    def _record(self, status, result, age_s, captured_s=None):
        track = self._track(result if status == LineStatus.FOUND else None,
                            time.monotonic() if captured_s is None else captured_s)
        packet = encode(status, result, self.sequence, age_s, track)
        self.sequence = (self.sequence + 1) & 0xFFFF
        record = {"status": status.name, "found": False, "offset": None, "angle_deg": None,
                  "confidence": 0.0, "candidates": 0}
        if result is not None:
            record.update(asdict(result))
        if status != LineStatus.FOUND:
            record.update(found=False, offset=None, angle_deg=None)
        return {**record, **track, "packet": packet.hex()}

    def process(self, frame):
        now = time.monotonic()
        recent = self.seen_at is not None and now - self.seen_at <= MEMORY_S
        previous = self.previous_offset if recent else None
        try:
            result = self.detector(frame.image, self.config, previous)
        except Exception as error:  # One bad frame must not stop line following; reported below.
            print(f"line detection failed: {type(error).__name__}: {error}", file=sys.stderr)
            return self._record(LineStatus.ERROR, None, frame.age_s())
        if frame.age_s() > self.config["max_frame_age_s"]:
            return self._record(LineStatus.NO_FRAME, None, frame.age_s())  # Processed too late.
        captured_s = frame.captured_ns / 1e9
        if result.found:
            self.previous_offset, self.seen_at = result.offset, captured_s
        status = LineStatus.FOUND if result.found else LineStatus.NO_LINE
        return self._record(status, result, frame.age_s(), captured_s)

    def no_frame(self):
        return self._record(LineStatus.NO_FRAME, None, None)


def main() -> int:
    config = load_config()
    stopping = False

    def request_stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    cv2.setNumThreads(1)  # One core is enough at max_fps; leaves the others to LiDAR and the rest.
    processor = LineProcessor(config)
    last_ns, count, started = None, 0, time.monotonic()
    last_output, next_at = started, started
    while not stopping:
        now = time.monotonic()
        if now < next_at:
            time.sleep(min(0.005, next_at - now))
            continue
        frame = read_frame(config["max_frame_age_s"], after_ns=last_ns)
        now = time.monotonic()
        if frame is not None:
            next_at = max(next_at, now) + 1 / config["max_fps"]
            last_ns, last_output = frame.captured_ns, now
            write_value("line", processor.process(frame), frame.captured_ns)
            count += 1
            continue
        if now - last_output >= config["max_frame_age_s"] + IDLE_REPORT_S:
            last_output = now - config["max_frame_age_s"]  # Then every IDLE_REPORT_S.
            write_value("line", processor.no_frame(), time.monotonic_ns())
        time.sleep(0.003)
    print(f"stopped: {count / (time.monotonic() - started):.1f} fps", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
