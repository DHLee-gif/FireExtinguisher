"""Raspberry Pi LiDAR-to-STM32 bridge.

Reads Camsense X1K-compatible 36-byte scan frames, groups them by revolution,
preserves per-zone measurement states, and emits a fixed-size UART packet.
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
import time
from dataclasses import dataclass, field
from enum import IntEnum
import serial

from lidar_data_processor import (
    SCAN_FRAME_SIZE,
    SCAN_HEADER,
    SDK_ANGLE_OFFSET_DEG,
    calc_camsense_checksum,
)


ZONE_NAMES = (
    "front",
    "front_right",
    "right",
    "rear_right",
    "rear",
    "rear_left",
    "left",
    "front_left",
)
EXPECTED_FRAMES_PER_REV = 52  # X1K SDK profile: ~415 points/rev, 8 points/frame.
HEADER = b"\xC3\x3C"
PROTOCOL_VERSION = 3
AGE_ESTIMATE_GUARD_MS = 100


class MeasurementStatus(IntEnum):
    VALID = 0
    TOO_CLOSE = 1
    TOO_FAR = 2
    NO_RETURN = 3
    SENSOR_INVALID = 4
    NO_DATA = 5


class CycleStatus(IntEnum):
    COMPLETE = 0
    PARTIAL = 1
    STARTUP_PARTIAL = 2


@dataclass
class ZoneValue:
    status: MeasurementStatus = MeasurementStatus.NO_DATA
    distance_mm: int = 0xFFFF
    quality: int = 0
    measured_at: float | None = None


@dataclass
class ScanCycle:
    sequence: int
    zones: list[ZoneValue] = field(default_factory=lambda: [ZoneValue() for _ in ZONE_NAMES])
    valid_frames: int = 0
    bad_frames: int = 0
    angular_coverage_deg: float = 0.0
    observed_zone_mask: int = 0
    speed_hz: float = 0.0
    # (bearing deg, status, distance mm, measured_at) of every point, for summaries beyond the 8 zones.
    points: list = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)

    def add_bad_frame(self) -> None:
        self.bad_frames = min(0xFFFF, self.bad_frames + 1)

    def add_frame(self, frame: bytes, forward_angle_deg: float, min_range_mm: int,
                  max_range_mm: int, measured_at: float | None = None) -> None:
        if measured_at is None:
            measured_at = time.monotonic()
        speed_raw = frame[4] | frame[5] << 8
        start_raw = frame[6] | frame[7] << 8
        end_raw = frame[32] | frame[33] << 8
        start = start_raw / 64.0 - 640.0
        end = end_raw / 64.0 - 640.0
        if end < start:
            end += 360.0
        # 8 points span 7 gaps; the 8th gap leads to the next frame's first point.
        self.angular_coverage_deg += max(0.0, min(360.0, (end - start) * 8.0 / 7.0))
        self.valid_frames = min(0xFFFF, self.valid_frames + 1)
        self.speed_hz = speed_raw / 3840.0
        step = (end - start) / 7.0

        for point_index in range(8):
            offset = 8 + point_index * 3
            raw = frame[offset] | frame[offset + 1] << 8
            distance = raw & 0x3FFF
            invalid_flag = bool(raw & 0x8000)
            quality = frame[offset + 2]
            angle = (start + step * point_index + SDK_ANGLE_OFFSET_DEG - forward_angle_deg) % 360.0
            bearing = (angle + 180.0) % 360.0 - 180.0
            zone_index = int((bearing + 22.5) // 45.0) % 8
            self.observed_zone_mask |= 1 << zone_index

            if invalid_flag:
                status, reported_distance = MeasurementStatus.SENSOR_INVALID, 0xFFFF
            elif distance == 0:
                status, reported_distance = MeasurementStatus.NO_RETURN, 0xFFFF
            elif distance < min_range_mm:
                status, reported_distance = MeasurementStatus.TOO_CLOSE, distance
            elif distance > max_range_mm:
                status, reported_distance = MeasurementStatus.TOO_FAR, distance
            else:
                status, reported_distance = MeasurementStatus.VALID, distance

            self.points.append((bearing, status, reported_distance, measured_at))
            current = self.zones[zone_index]
            self.zones[zone_index] = _merge_zone_value(
                current, ZoneValue(status, reported_distance, quality, measured_at)
            )


def _merge_zone_value(current: ZoneValue, candidate: ZoneValue) -> ZoneValue:
    """Keep the nearest meaningful return, retaining explicit absence/error states."""
    rank = {
        MeasurementStatus.TOO_CLOSE: 0,
        MeasurementStatus.VALID: 1,
        MeasurementStatus.TOO_FAR: 2,
        MeasurementStatus.SENSOR_INVALID: 3,
        MeasurementStatus.NO_RETURN: 4,
        MeasurementStatus.NO_DATA: 5,
    }
    if rank[candidate.status] < rank[current.status]:
        return candidate
    if (candidate.status == current.status
            and candidate.status in (MeasurementStatus.NO_RETURN, MeasurementStatus.SENSOR_INVALID)):
        return candidate
    if candidate.status == current.status and candidate.distance_mm < current.distance_mm:
        return candidate
    return current


def encode_cycle(cycle: ScanCycle, *, sequence: int, cycle_status: CycleStatus,
                 max_unobserved_travel_mm: int) -> bytes:
    packet_time = time.monotonic()
    speed_mhz = min(0xFFFF, max(0, round(cycle.speed_hz * 1000.0)))
    period_ms = min(0xFFFF, round(1000.0 / cycle.speed_hz)) if cycle.speed_hz > 0 else 0xFFFF
    elapsed_ms = min(0xFFFF, max(0, round((time.monotonic() - cycle.started_at) * 1000.0)))
    # Include both nominal sensor period and measured collection/reconnect delay.
    effective_delay_ms = max(period_ms if period_ms != 0xFFFF else 0, elapsed_ms)
    max_speed_mm_s = min(0xFFFF, round(max_unobserved_travel_mm * 1000 / effective_delay_ms)) if effective_delay_ms and max_unobserved_travel_mm else 0xFFFF
    frame = bytearray(HEADER)
    frame.extend((PROTOCOL_VERSION, int(cycle_status)))
    frame.extend(struct.pack("<HHHHHHH", sequence & 0xFFFF, cycle.valid_frames,
                             cycle.bad_frames, speed_mhz, period_ms, elapsed_ms,
                             max_speed_mm_s))
    frame.append(cycle.observed_zone_mask)
    for zone in cycle.zones:
        frame.append(int(zone.status))
        frame.extend(struct.pack("<H", zone.distance_mm))
        frame.append(zone.quality)
        if zone.measured_at is None:
            age_ms = 0xFFFF
        else:
            age_ms = min(
                0xFFFE,
                max(0, math.ceil((packet_time - zone.measured_at) * 1000)
                    + AGE_ESTIMATE_GUARD_MS),
            )
        frame.extend(struct.pack("<H", age_ms))
    frame.extend(struct.pack("<H", crc16_ccitt_false(frame)))
    return bytes(frame)


def crc16_ccitt_false(data: bytes | bytearray) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def is_complete(cycle: ScanCycle, expected_frames: int) -> bool:
    return (cycle.angular_coverage_deg >= 350.0
            and cycle.valid_frames >= math.ceil(expected_frames * 0.90)
            and cycle.observed_zone_mask == 0xFF
            and cycle.bad_frames == 0)


def open_serial_with_retry(port: str, baud: int, label: str):
    """Try once plus a bounded number of reconnect attempts with backoff."""
    delay_s = 1.0
    retries = 0
    max_retries = 5
    while True:
        try:
            device = serial.Serial(port, baud, timeout=0.05, write_timeout=1.0)
            print(f"{label} connected: {port} @ {baud}", file=sys.stderr)
            return device
        except (serial.SerialException, OSError) as error:
            if retries >= max_retries:
                raise RuntimeError(
                    f"{label} unavailable on {port} after {retries + 1} attempts: {error}"
                ) from error
            retries += 1
            print(f"{label} unavailable on {port}: {error}; retry {retries}/{max_retries} in {delay_s:.0f}s",
                  file=sys.stderr)
            time.sleep(delay_s)
            delay_s = min(delay_s * 2.0, 10.0)


def close_serial(device) -> None:
    if device is None:
        return
    try:
        device.close()
    except (serial.SerialException, OSError):
        pass


class FrameStream:
    """Incrementally frame a byte stream and report valid or damaged candidates."""

    def __init__(self) -> None:
        self.buffer = bytearray()

    def feed(self, data: bytes):
        self.buffer.extend(data)
        while True:
            offset = self.buffer.find(SCAN_HEADER)
            if offset < 0:
                keep = 0
                for size in range(min(len(self.buffer), len(SCAN_HEADER) - 1), 0, -1):
                    if self.buffer[-size:] == SCAN_HEADER[:size]:
                        keep = size
                        break
                if keep:
                    del self.buffer[:-keep]
                else:
                    self.buffer.clear()
                return
            if offset:
                del self.buffer[:offset]
            if len(self.buffer) < SCAN_FRAME_SIZE:
                return
            candidate = bytes(self.buffer[:SCAN_FRAME_SIZE])
            if candidate[2:4] != b"\x03\x08" or calc_camsense_checksum(candidate) != (candidate[34] | candidate[35] << 8):
                del self.buffer[0]
                yield None
                continue
            if (candidate[6] | candidate[7] << 8) < 0xA000 or (candidate[32] | candidate[33] << 8) < 0xA000:
                del self.buffer[0]
                yield None
                continue
            del self.buffer[:SCAN_FRAME_SIZE]
            yield candidate


def run(args: argparse.Namespace) -> None:
    if not 1 <= args.min_range_mm <= args.max_range_mm <= 0x3FFF:
        raise ValueError("distance limits must satisfy 1 <= min <= max <= 16383 mm")
    if args.expected_frames < 1:
        raise ValueError("expected-frames must be positive")
    if args.max_unobserved_travel_mm < 0:
        raise ValueError("max-unobserved-travel-mm cannot be negative")
    if not math.isfinite(args.forward_angle):
        raise ValueError("forward-angle must be a finite number")
    source = None
    destination = None
    sequence = 0
    cycle = ScanCycle(sequence)
    stream = FrameStream()
    previous_start: float | None = None
    first_cycle = True
    last_cycle_emit = time.monotonic()
    try:
        destination = open_serial_with_retry(args.stm32_port, args.stm32_baud, "STM32 UART")
        source = open_serial_with_retry(args.lidar_port, args.lidar_baud, "LiDAR UART")

        def send_packet(packet: bytes) -> bool:
            nonlocal destination
            try:
                written = destination.write(packet)
                if written != len(packet):
                    raise serial.SerialException(
                        f"short STM32 write: {written}/{len(packet)} bytes"
                    )
                return True
            except (serial.SerialException, OSError) as error:
                print(f"STM32 UART write failed: {error}; reconnecting; dropping stale packet",
                      file=sys.stderr)
                close_serial(destination)
                destination = open_serial_with_retry(
                    args.stm32_port, args.stm32_baud, "STM32 UART"
                )
                return False

        print(f"LiDAR {args.lidar_port} -> STM32 {args.stm32_port}; Ctrl+C to stop", file=sys.stderr)
        while True:
            read_started_at = time.monotonic()
            try:
                incoming = source.read(512)
            except (serial.SerialException, OSError) as error:
                print(f"LiDAR UART read failed: {error}; reconnecting", file=sys.stderr)
                close_serial(source)
                source = open_serial_with_retry(args.lidar_port, args.lidar_baud, "LiDAR UART")
                stream = FrameStream()
                previous_start = None
                first_cycle = False
                delivered = send_packet(encode_cycle(
                    cycle,
                    sequence=sequence,
                    cycle_status=CycleStatus.PARTIAL,
                    max_unobserved_travel_mm=args.max_unobserved_travel_mm,
                ))
                sequence = (sequence + 1) & 0xFFFF
                if not delivered:
                    try:
                        source.reset_input_buffer()
                    except (AttributeError, serial.SerialException, OSError):
                        pass
                cycle = ScanCycle(sequence)
                last_cycle_emit = time.monotonic()
                continue

            transport_recovered = False
            for frame in stream.feed(incoming):
                if frame is None:
                    if cycle is not None:
                        cycle.add_bad_frame()
                    continue
                start = ((frame[6] | frame[7] << 8) / 64.0 - 640.0) % 360.0
                if previous_start is not None and previous_start - start > 180.0:
                    if cycle is not None:
                        complete = is_complete(cycle, args.expected_frames)
                        status = (CycleStatus.STARTUP_PARTIAL if first_cycle else
                                  CycleStatus.COMPLETE if complete else CycleStatus.PARTIAL)
                        packet = encode_cycle(cycle, sequence=sequence, cycle_status=status,
                                              max_unobserved_travel_mm=args.max_unobserved_travel_mm)
                        if not send_packet(packet):
                            sequence = (sequence + 1) & 0xFFFF
                            try:
                                source.reset_input_buffer()
                            except (AttributeError, serial.SerialException, OSError):
                                pass
                            stream = FrameStream()
                            previous_start = None
                            first_cycle = False
                            cycle = ScanCycle(sequence)
                            last_cycle_emit = time.monotonic()
                            transport_recovered = True
                            break
                        sequence = (sequence + 1) & 0xFFFF
                        last_cycle_emit = time.monotonic()
                    cycle = ScanCycle(sequence)
                    first_cycle = False
                if cycle is None:
                    cycle = ScanCycle(sequence)
                cycle.add_frame(
                    frame,
                    args.forward_angle,
                    args.min_range_mm,
                    args.max_range_mm,
                    measured_at=read_started_at,
                )
                previous_start = start
            if transport_recovered:
                continue
            if cycle is not None:
                scan_period_s = 1.0 / cycle.speed_hz if cycle.speed_hz > 0 else 0.2
                partial_timeout_s = max(0.5, 2.0 * scan_period_s)
                if time.monotonic() - last_cycle_emit >= partial_timeout_s:
                    packet = encode_cycle(
                        cycle,
                        sequence=sequence,
                        cycle_status=CycleStatus.PARTIAL,
                        max_unobserved_travel_mm=args.max_unobserved_travel_mm,
                    )
                    delivered = send_packet(packet)
                    sequence = (sequence + 1) & 0xFFFF
                    cycle = ScanCycle(sequence)
                    previous_start = None
                    last_cycle_emit = time.monotonic()
                    if not delivered:
                        try:
                            source.reset_input_buffer()
                        except (AttributeError, serial.SerialException, OSError):
                            pass
                        stream = FrameStream()
        
    except KeyboardInterrupt:
        print("\nStopped", file=sys.stderr)
    finally:
        close_serial(source)
        close_serial(destination)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lidar-port", required=True, help="LiDAR UART device, e.g. /dev/ttyUSB0")
    parser.add_argument("--stm32-port", required=True, help="STM32 UART device, e.g. /dev/ttyACM0")
    parser.add_argument("--lidar-baud", type=int, default=115200)
    parser.add_argument("--stm32-baud", type=int, default=115200)
    parser.add_argument("--forward-angle", type=float, default=0.0, help="Measured sensor forward angle in degrees")
    parser.add_argument("--min-range-mm", type=int, default=120)
    parser.add_argument("--max-range-mm", type=int, default=8000)
    parser.add_argument("--expected-frames", type=int, default=EXPECTED_FRAMES_PER_REV)
    parser.add_argument("--max-unobserved-travel-mm", type=int, default=0,
                        help="Set only after vehicle safety analysis; 0 reports unknown speed bound")
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
