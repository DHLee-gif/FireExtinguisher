"""Latest-frame exchange between independent processes.

The writer replaces one file in RAM atomically. Readers never lock it, so a slow or
dead reader cannot block the camera, and a reader never sees a half-written frame.
"""

from __future__ import annotations

import os
import struct
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

DEFAULT_PATH = Path("/dev/shm/firecar/frame.bin")
MAGIC = b"FCF1"
HEADER = struct.Struct("<4sIQHH")  # magic, sequence, monotonic ns, width, height


@dataclass(frozen=True)
class Frame:
    image: np.ndarray  # height x width x 3, BGR (OpenCV order), read-only
    sequence: int
    captured_ns: int

    def age_s(self) -> float:
        return (time.monotonic_ns() - self.captured_ns) / 1e9


def write_frame(image: np.ndarray, sequence: int, captured_ns: int,
                path: Path = DEFAULT_PATH) -> None:
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"expected HxWx3 uint8, got {image.shape} {image.dtype}")
    height, width = image.shape[:2]
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "wb", buffering=0) as output:
        output.write(HEADER.pack(MAGIC, sequence & 0xFFFFFFFF, captured_ns, width, height))
        output.write(np.ascontiguousarray(image).data)
    os.replace(temporary, path)


def read_frame(max_age_s: float, path: Path = DEFAULT_PATH,
               after_ns: int | None = None) -> Frame | None:
    """Return the latest frame, or None when it is missing, damaged, or too old.

    With after_ns, also return None (cheaply) while the frame is still that one.
    """
    try:
        with open(path, "rb", buffering=0) as source:
            header = source.read(HEADER.size)
            if len(header) < HEADER.size:
                return None
            magic, sequence, captured_ns, width, height = HEADER.unpack(header)
            if magic != MAGIC or captured_ns == after_ns:
                return None
            data = source.readall()
    except FileNotFoundError:
        return None
    if len(data) != width * height * 3:
        return None
    image = np.frombuffer(data, np.uint8).reshape(height, width, 3)
    frame = Frame(image, sequence, captured_ns)
    # A negative age means the file is from another boot.
    return frame if 0 <= frame.age_s() <= max_age_s else None
