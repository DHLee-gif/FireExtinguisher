"""LiDAR process: sensor bytes -> shared "lidar" value with the v3 69-byte packet.

Runs forever: a missing or unplugged sensor is reported and retried.
--replay FILE.hex feeds a recorded capture at sensor speed instead.
"""

from __future__ import annotations

import argparse
import math
import signal
import sys
import time
import tomllib
from pathlib import Path

import serial

from common.valuebus import write_value
from summary import encode as encode_summary
from summary import oldest_age_ms, summarize
from lidar_bridge import (
    ZONE_NAMES, CycleStatus, FrameStream, ScanCycle, close_serial, encode_cycle, is_complete,
)

CONFIG_PATH = Path(__file__).with_name("config.toml")
RETRY_S = 1.0
MAX_BACKLOG_BYTES = 1024  # About 90 ms of sensor data; more means we fell behind.


def load_config(path: Path = CONFIG_PATH) -> dict:
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    if not 1 <= config["min_range_mm"] <= config["max_range_mm"] <= 0x3FFF:
        raise ValueError("need 1 <= min_range_mm <= max_range_mm <= 16383")
    if config["expected_frames"] < 1 or config["baud"] <= 0 or not config["port"]:
        raise ValueError("expected_frames, baud, and port must be set")
    if not (0 < config["car_width_mm"] <= 2000 and 0 <= config["side_margin_mm"] <= 1000
            and 0 < config["side_lookahead_mm"] <= 8000):
        raise ValueError("car_width_mm, side_margin_mm, side_lookahead_mm out of range")
    if not math.isfinite(config["forward_angle_deg"]):
        raise ValueError("forward_angle_deg must be finite")
    return config


class CycleBuilder:
    """Group sensor bytes into revolutions; also closes a revolution that stalls."""

    def __init__(self, config: dict) -> None:
        self.config = config
        self.sequence = 0
        self.first = True
        self.reset()

    def reset(self) -> None:
        """Drop unfinished data, e.g. after the sensor was reconnected."""
        self.stream = FrameStream()
        self.previous_start = None
        self.previous_end = None
        self.lossy = False
        self.cycle = ScanCycle(self.sequence)

    def _finish(self, status: CycleStatus) -> dict:
        now = time.monotonic()
        measured = [zone.measured_at for zone in self.cycle.zones if zone.measured_at is not None]
        packet = encode_cycle(self.cycle, sequence=self.sequence, cycle_status=status,
                              max_unobserved_travel_mm=0)
        summary = summarize(self.cycle.points, self.config)
        oldest_ms = oldest_age_ms(self.cycle.points, now)
        record = {
            "status": status.name,
            "summary": summary,
            "summary_packet": encode_summary(summary, status, self.sequence, oldest_ms).hex(),
            "sequence": self.sequence,
            "speed_hz": round(self.cycle.speed_hz, 3),
            "valid_frames": self.cycle.valid_frames,
            "bad_frames": self.cycle.bad_frames,
            "zones": {name: {"status": zone.status.name,
                             "distance_mm": None if zone.distance_mm == 0xFFFF else zone.distance_mm,
                             "quality": zone.quality,
                             "age_ms": None if zone.measured_at is None
                             else round((now - zone.measured_at) * 1000)}
                      for name, zone in zip(ZONE_NAMES, self.cycle.zones)},
            "packet": packet.hex(),
            # The ages inside the packet are as of packet_ns: a sender must add its own delay.
            "packet_ns": round(now * 1e9),
            "captured_ns": round(min(measured, default=now) * 1e9),  # Oldest zone.
        }
        self.sequence = (self.sequence + 1) & 0xFFFF
        self.cycle = ScanCycle(self.sequence)
        self.lossy = False
        return record

    def feed(self, data: bytes, measured_at: float) -> list[dict]:
        records = []
        for frame in self.stream.feed(data):
            if frame is None:
                self.cycle.add_bad_frame()
                continue
            start = ((frame[6] | frame[7] << 8) / 64.0 - 640.0) % 360.0
            end = ((frame[32] | frame[33] << 8) / 64.0 - 640.0) % 360.0
            # Neighbouring frames are one point spacing apart; a wider gap is a lost frame.
            gap = (self.previous_end is not None
                   and (start - self.previous_end) % 360.0 > 3.0 * ((end - start) % 360.0) / 7.0)
            self.lossy |= gap
            # Frames always move forward, so any decrease is a new revolution.
            if self.previous_start is not None and start < self.previous_start:
                period = 1.0 / self.cycle.speed_hz if self.cycle.speed_hz > 0 else 0.2
                # A whole lost revolution leaves no angle gap, only extra time.
                late = time.monotonic() - self.cycle.started_at > 1.5 * period
                status = (CycleStatus.STARTUP_PARTIAL if self.first else
                          CycleStatus.COMPLETE if not self.lossy and not late
                          and is_complete(self.cycle, self.config["expected_frames"])
                          else CycleStatus.PARTIAL)
                records.append(self._finish(status))
                self.first = False
                self.lossy = gap  # A loss across the wrap may belong to either side.
            self.cycle.add_frame(frame, self.config["forward_angle_deg"], self.config["min_range_mm"],
                                 self.config["max_range_mm"], measured_at=measured_at)
            self.previous_start, self.previous_end = start, end
        period = 1.0 / self.cycle.speed_hz if self.cycle.speed_hz > 0 else 0.2
        if time.monotonic() - self.cycle.started_at >= max(0.5, 2.0 * period):
            records.append(self._finish(CycleStatus.PARTIAL))
            self.previous_start = self.previous_end = None
        return records


class Replay:
    """Stand-in for the serial port: loops a capture at 115200 baud speed."""

    in_waiting = 0

    def __init__(self, path: Path) -> None:
        self.data = bytes.fromhex(path.read_text())
        if not self.data:
            raise ValueError(f"empty capture: {path}")
        self.position = 0

    def read(self, size: int) -> bytes:
        chunk = self.data[self.position:self.position + size]
        self.position = (self.position + size) % len(self.data) if chunk else 0
        if self.position < size:
            self.position = 0
        time.sleep(len(chunk) / 11520)
        return chunk

    def close(self) -> None:
        self.position = 0


def step(open_source, source, builder: CycleBuilder):
    """Read once. Returns (source or None when disconnected, finished records)."""
    try:
        if source is None:
            source = open_source()
            print("LiDAR connected", file=sys.stderr)
            builder.reset()
        if source.in_waiting > MAX_BACKLOG_BYTES:
            print(f"LiDAR backlog {source.in_waiting} bytes dropped", file=sys.stderr)
            source.reset_input_buffer()
            builder.reset()
        measured_at = time.monotonic()
        return source, builder.feed(source.read(512), measured_at)
    except (serial.SerialException, OSError) as error:
        print(f"LiDAR unavailable: {error}; retrying", file=sys.stderr)
        close_serial(source)
        builder.reset()
        return None, [builder._finish(CycleStatus.PARTIAL)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    config = load_config()
    stopping = False

    def request_stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    def open_source():
        if args.replay:
            return Replay(args.replay)
        return serial.Serial(config["port"], config["baud"], timeout=0.05)

    builder, source = CycleBuilder(config), None
    while not stopping:
        source, records = step(open_source, source, builder)
        for record in records:
            write_value("lidar", {**record, "connected": source is not None,
                                  "replay": bool(args.replay)}, record["captured_ns"])
        if source is None:
            time.sleep(RETRY_S)
    close_serial(source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
