"""Fire result -> 22-byte packet for the STM32. Layout: docs/fire.md"""

from __future__ import annotations

import struct
from enum import IntEnum

from detector import Detection

HEADER = b"\xC3\x6C"
VERSION = 1
NO_INT16 = 0x7FFF
NO_UINT16 = 0xFFFF


class FireStatus(IntEnum):
    FIRE = 0       # Seen in enough recent frames: confirmed fire.
    NO_FIRE = 1    # Picture is fine and no fire in it.
    SUSPECT = 2    # Seen, but not in enough frames yet. Do not act as fire.
    NO_FRAME = 3   # No recent camera image: fire value unknown.
    ERROR = 4      # Detection failed: fire value unknown.
    NO_MODEL = 5   # Model file missing or unusable: fire value unknown.


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def _ms(seconds: float | None) -> int:
    return NO_UINT16 if seconds is None else min(0xFFFE, max(0, round(seconds * 1000)))


def encode(status: FireStatus, sequence: int, target: Detection | None, seen_s: float | None,
           hits: int, window: int, candidates: int, age_s: float | None) -> bytes:
    """target: most recent fire box (may be from an earlier frame, then seen_s > 0)."""
    x, y, size, confidence = NO_INT16, NO_UINT16, NO_UINT16, 0
    if target is not None:
        x = max(-1000, min(1000, round(target.x * 1000)))
        y = max(0, min(1000, round(target.y * 1000)))
        size = max(0, min(1000, round(target.width * target.height * 1000)))
        confidence = max(0, min(100, round(target.score * 100)))
    body = HEADER + struct.pack(
        "<BBHhHHBBBBHH", VERSION, status, sequence & 0xFFFF, x, y, size, confidence,
        min(255, hits), min(255, window), min(255, candidates), _ms(seen_s), _ms(age_s))
    return body + struct.pack("<H", crc16_ccitt_false(body))
