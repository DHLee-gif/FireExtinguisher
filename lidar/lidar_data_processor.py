"""Decode Camsense X1 packets and summarize obstacle distances by vehicle zone."""

from __future__ import annotations

from typing import Iterable


SCAN_HEADER = b"\x55\xaa\x03\x08"
SCAN_FRAME_SIZE = 36
SCAN_SAMPLE_COUNT = 8
SDK_ANGLE_OFFSET_DEG = 28.5
ZONE_RANGES_DEG = (
    ("전방", -22.5, 22.5),
    ("전방 우측", 22.5, 67.5),
    ("우측", 67.5, 112.5),
    ("후방 우측", 112.5, 157.5),
    ("후방", 157.5, -157.5),
    ("후방 좌측", -157.5, -112.5),
    ("좌측", -112.5, -67.5),
    ("전방 좌측", -67.5, -22.5),
)

Point = tuple[float, int, int]


def calc_camsense_checksum(packet: bytes) -> int:
    """Return the Camsense 15-bit shift-and-fold checksum for a 36-byte packet."""
    if len(packet) != SCAN_FRAME_SIZE:
        raise ValueError(f"Expected a {SCAN_FRAME_SIZE}-byte scan packet")

    accumulator = 0
    for offset in range(0, 34, 2):
        word = packet[offset] | (packet[offset + 1] << 8)
        accumulator = ((accumulator << 1) + word) & 0xFFFFFFFF

    return ((accumulator & 0x7FFF) + (accumulator >> 15)) & 0x7FFF


def parse_scan_frame(
    packet: bytes,
    angle_offset_deg: float = SDK_ANGLE_OFFSET_DEG,
) -> tuple[float, list[Point]]:
    """Decode a validated Camsense X1 frame into frequency and valid points."""
    if len(packet) != SCAN_FRAME_SIZE:
        raise ValueError(f"Expected a {SCAN_FRAME_SIZE}-byte scan packet")
    if packet[:4] != SCAN_HEADER:
        raise ValueError("Invalid Camsense X1 scan header")

    received_checksum = packet[34] | (packet[35] << 8)
    if calc_camsense_checksum(packet) != received_checksum:
        raise ValueError("Invalid Camsense X1 scan checksum")

    speed_raw = packet[4] | (packet[5] << 8)
    start_raw = packet[6] | (packet[7] << 8)
    end_raw = packet[32] | (packet[33] << 8)
    if start_raw < 0xA000 or end_raw < 0xA000:
        raise ValueError("Camsense X1 angle is below its 0xA000 base")

    start_angle = start_raw / 64.0 - 640.0
    end_angle = end_raw / 64.0 - 640.0
    if end_angle < start_angle:
        end_angle += 360.0
    angle_step = (end_angle - start_angle) / (SCAN_SAMPLE_COUNT - 1)

    points: list[Point] = []
    for index in range(SCAN_SAMPLE_COUNT):
        offset = 8 + index * 3
        raw_distance = packet[offset] | (packet[offset + 1] << 8)
        distance_mm = raw_distance & 0x3FFF
        invalid_flag = bool(raw_distance & 0x8000)
        quality = packet[offset + 2]
        if invalid_flag or distance_mm == 0:
            continue

        angle = (start_angle + angle_step * index + angle_offset_deg) % 360.0
        points.append((angle, distance_mm, quality))

    return speed_raw / 3840.0, points


def calculate_zone_minima(
    points: Iterable[Point],
    forward_angle_deg: float = 0.0,
    min_range_mm: int = 120,
    max_range_mm: int = 8000,
) -> dict[str, int | None]:
    """Return nearest valid distance in eight 45-degree compass zones."""
    minima = {name: None for name, _, _ in ZONE_RANGES_DEG}

    for angle, distance_mm, _ in points:
        if not min_range_mm <= distance_mm <= max_range_mm:
            continue

        bearing = (angle - forward_angle_deg + 180.0) % 360.0 - 180.0
        for name, lower, upper in ZONE_RANGES_DEG:
            is_in_zone = (
                lower <= bearing < upper
                if lower < upper
                else bearing >= lower or bearing < upper
            )
            if is_in_zone:
                nearest = minima[name]
                if nearest is None or distance_mm < nearest:
                    minima[name] = distance_mm
                break

    return minima
