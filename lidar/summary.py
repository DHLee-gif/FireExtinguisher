"""Driving summary of one revolution: what the STM32 needs beyond 8 coarse zones.

Coordinates: LiDAR at the origin, x forward, y right (mm). Bearing 0 = forward, + = right.
Only VALID points count as obstacles; TOO_CLOSE points are counted separately, because
below the minimum range they may be the car's own body.
"""

from __future__ import annotations

import math
import struct

from lidar_bridge import MeasurementStatus, crc16_ccitt_false

HEADER = b"\xC3\x5C"
VERSION = 1
UNKNOWN = 0xFFFF   # Not observed this revolution.
CLEAR = 0xFFFE     # Observed, no obstacle up to the maximum range.
NO_BEARING = 0x7FFF

# An area counts as seen only when every 10-degree step of its bearings got a point.
# Front: corridor obstacles from about 170 mm on. Sides: the strip next to the car.
REGIONS = {"front": (-60, 60), "left": (-90, 0), "right": (0, 90)}
AGE_GUARD_MS = 100  # Same input-buffer margin as the v3 packet ages.

FLAG_TOO_CLOSE_AHEAD = 0x01   # Something under the minimum range inside the corridor.
FLAG_NO_RETURN_AHEAD = 0x02   # Some forward points returned nothing (black or far).


def summarize(points, config: dict) -> dict:
    half = config["car_width_mm"] / 2 + config["side_margin_mm"]
    front = left = right = nearest = None
    nearest_bearing = None
    steps = {math.floor(bearing / 10) for bearing, *_ in points}
    observed = {name: all(step in steps for step in range(low // 10, high // 10))
                for name, (low, high) in REGIONS.items()}
    flags = 0
    for bearing, status, distance, *_ in points:
        radians = math.radians(bearing)
        ahead = -90.0 < bearing < 90.0
        if ahead and status == MeasurementStatus.NO_RETURN:
            flags |= FLAG_NO_RETURN_AHEAD
        if status == MeasurementStatus.TOO_CLOSE and ahead and abs(distance * math.sin(radians)) <= half:
            flags |= FLAG_TOO_CLOSE_AHEAD
        if status != MeasurementStatus.VALID:
            continue
        x, y = distance * math.cos(radians), distance * math.sin(radians)
        if nearest is None or distance < nearest:
            nearest, nearest_bearing = distance, bearing
        if x > 0 and abs(y) <= half and (front is None or x < front):
            front = x
        if 0 <= x <= config["side_lookahead_mm"]:
            if y > 0 and (right is None or y < right):
                right = y
            if y < 0 and (left is None or -y < left):
                left = -y

    def value(found, seen):
        # Part of the area unseen: a closer obstacle may hide there, so never report a distance.
        if not seen:
            return UNKNOWN
        return CLEAR if found is None else round(found)

    return {
        "front_clear_mm": value(front, observed["front"]),
        "left_clear_mm": value(left, observed["left"]),
        "right_clear_mm": value(right, observed["right"]),
        # Nearest over whatever was seen; the cycle status says whether that was a full turn.
        "nearest_mm": UNKNOWN if not points else CLEAR if nearest is None else round(nearest),
        "nearest_bearing_deg": None if nearest_bearing is None else round(nearest_bearing, 1),
        "flags": flags,
    }


def oldest_age_ms(points, now: float) -> int:
    """Age of the oldest point of the revolution, with the same margin as v3."""
    times = [point[3] for point in points if len(point) > 3 and point[3] is not None]
    if not times:
        return 0xFFFF
    return min(0xFFFE, max(0, math.ceil((now - min(times)) * 1000) + AGE_GUARD_MS))


def encode(summary: dict, cycle_status: int, sequence: int, age_ms: int) -> bytes:
    bearing = summary["nearest_bearing_deg"]
    body = HEADER + struct.pack(
        "<BBHHHHHhBH", VERSION, cycle_status, sequence & 0xFFFF,
        summary["front_clear_mm"], summary["left_clear_mm"], summary["right_clear_mm"],
        summary["nearest_mm"], NO_BEARING if bearing is None else round(bearing * 10),
        summary["flags"], min(0xFFFF, age_ms))
    return body + struct.pack("<H", crc16_ccitt_false(body))
