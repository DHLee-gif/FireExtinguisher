"""Pick new packets from the shared values and make them ready to send to the STM32.

Other processes (line/, lidar/, fire/) already build the packets and leave them, hex-encoded, in
/dev/shm/firecar/<name>.json. This module only:
  - sends each packet once (a new Sequence); a dead process leaves its last file behind,
  - adds the time the packet waited here to its age fields and recomputes the CRC,
  - drops packets that waited too long, and anything that is not a valid packet.
Packet layouts: docs/line_packet.md, docs/lidar_packet.md, docs/fire.md, docs/stm32_link.md
"""

from __future__ import annotations

import json
import os
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

SYNC = 0xC3
NO_U16 = 0xFFFF
MAX_U16 = 0xFFFE

# Second header byte -> (total length, offsets of uint16 age fields in ms).
LAYOUTS = {
    0x3C: (69, tuple(19 + 6 * i + 4 for i in range(8))),  # LiDAR v3: age of each of 8 zones
    0x4C: (25, (21,)),                                     # line v2: Age
    0x5C: (21, (17,)),                                     # LiDAR driving summary v1: Age
    0x6C: (22, (16, 18)),                                  # fire v1: Seen, Age
}


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def is_valid(packet: bytes) -> bool:
    layout = LAYOUTS.get(packet[1]) if len(packet) >= 2 and packet[0] == SYNC else None
    return (layout is not None and len(packet) == layout[0]
            and crc16_ccitt_false(packet[:-2]) == struct.unpack_from("<H", packet, len(packet) - 2)[0])


def sequence_of(packet: bytes) -> int:
    return struct.unpack_from("<H", packet, 4)[0]


def add_delay(packet: bytes, delay_ms: int) -> bytes:
    """Age fields grow by the time the packet waited; "no value" (0xFFFF) stays as it is."""
    data = bytearray(packet)
    for offset in LAYOUTS[data[1]][1]:
        age = struct.unpack_from("<H", data, offset)[0]
        if age != NO_U16:
            struct.pack_into("<H", data, offset, min(MAX_U16, age + max(0, delay_ms)))
    struct.pack_into("<H", data, len(data) - 2, crc16_ccitt_false(bytes(data[:-2])))
    return bytes(data)


@dataclass
class Stats:
    sent: dict = field(default_factory=dict)      # "lidar.packet" -> count
    stale: int = 0       # waited longer than max_delay_ms
    invalid: int = 0     # not a packet we know, or bad CRC
    unreadable: int = 0  # file missing a field or half-written

    def text(self) -> str:
        sent = " ".join(f"{name}={count}" for name, count in sorted(self.sent.items())) or "none"
        return f"sent {sent} | stale {self.stale} invalid {self.invalid} unreadable {self.unreadable}"


class PacketPicker:
    """sources: {value name: [packet fields]}, e.g. {"lidar": ["summary_packet", "packet"]}."""

    def __init__(self, folder: Path, sources: dict[str, list[str]], max_delay_ms: int) -> None:
        self.folder, self.sources, self.max_delay_ms = folder, sources, max_delay_ms
        self.last_mtime: dict[str, int] = {}
        self.last_sequence: dict[str, int] = {}
        self.stats = Stats()

    def poll(self, now_ns: int | None = None) -> list[bytes]:
        """Packets to send now, oldest source first. Reads a file only when it changed."""
        out = []
        for name, fields in self.sources.items():
            path = self.folder / f"{name}.json"
            try:
                mtime = os.stat(path).st_mtime_ns
            except FileNotFoundError:
                continue  # That process has not started yet.
            if self.last_mtime.get(name) == mtime:
                continue
            self.last_mtime[name] = mtime
            try:
                value = json.loads(path.read_text())["value"]
            except (FileNotFoundError, ValueError, KeyError, TypeError):
                self.stats.unreadable += 1
                continue
            # The file is written right after the packet is made, so its time = packet time.
            delay_ms = round(((time.time_ns() if now_ns is None else now_ns) - mtime) / 1e6)
            for key in fields:
                packet = self._pick(value, key, f"{name}.{key}", delay_ms)
                if packet is not None:
                    out.append(packet)
        return out

    def _pick(self, value: dict, key: str, label: str, delay_ms: int) -> bytes | None:
        text = value.get(key)
        if not isinstance(text, str):
            return None  # e.g. no summary in this record.
        try:
            packet = bytes.fromhex(text)
        except ValueError:
            self.stats.invalid += 1
            return None
        if not is_valid(packet):
            self.stats.invalid += 1
            return None
        sequence = sequence_of(packet)
        if self.last_sequence.get(label) == sequence:
            return None  # Already sent (same file content rewritten, or a dead process).
        self.last_sequence[label] = sequence
        if delay_ms > self.max_delay_ms:
            self.stats.stale += 1
            return None
        self.stats.sent[label] = self.stats.sent.get(label, 0) + 1
        return add_delay(packet, delay_ms)
