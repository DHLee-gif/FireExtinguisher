"""Line result -> 25-byte packet for the STM32. Layout: docs/line_packet.md"""

from __future__ import annotations

import struct
from enum import IntEnum

from detector import LineResult

HEADER = b"\xC3\x4C"
VERSION = 2
NO_INT16 = 0x7FFF


class LineStatus(IntEnum):
    FOUND = 0
    NO_LINE = 1   # Image is fine, no line in it.
    NO_FRAME = 2  # No recent camera image.
    ERROR = 3     # Processing failed.


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode(status: LineStatus, result: LineResult | None, sequence: int, age_s: float | None,
           track: dict | None = None) -> bytes:
    """track: smoothed values from LineProcessor (see docs/line_packet.md)."""
    offset = angle = NO_INT16
    confidence = candidates = 0
    if result is not None:
        confidence, candidates = round(result.confidence * 100), min(255, result.candidates)
        if status == LineStatus.FOUND:
            offset, angle = round(result.offset * 1000), round(result.angle_deg * 100)
    track = track or {}

    def scaled(key, factor):
        value = track.get(key)
        return NO_INT16 if value is None else max(-32767, min(32766, round(value * factor)))

    lost = track.get("lost_ms")
    age_ms = 0xFFFF if age_s is None else min(0xFFFE, max(0, round(age_s * 1000)))
    body = HEADER + struct.pack(
        "<BBHhhhhhBBbHH", VERSION, status, sequence & 0xFFFF, offset, angle,
        scaled("smooth_offset", 1000), scaled("smooth_angle_deg", 100), scaled("offset_rate", 1000),
        confidence, candidates, track.get("last_side", 0),
        0xFFFF if lost is None else min(0xFFFE, lost), age_ms)
    return body + struct.pack("<H", crc16_ccitt_false(body))
