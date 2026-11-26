"""Find one line in an image. Pure computation: no camera, files, or motors."""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

CONFIG_PATH = Path(__file__).with_name("config.toml")
MIN_ROWS = 8


@dataclass(frozen=True)
class LineResult:
    """offset: -1 left edge .. 0 center .. +1 right edge, at the bottom of the ROI.
    angle_deg: image-plane tilt; 0 straight ahead, + means the line leans right ahead.
    Both are None when no line was found."""

    found: bool
    offset: float | None
    angle_deg: float | None
    confidence: float
    candidates: int = 0  # 2 or more: several possible lines were visible


def load_config(path: Path = CONFIG_PATH) -> dict:
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    if config["color"] not in config["colors"]:
        raise ValueError(f"unknown color: {config['color']}")
    if not (0 <= config["roi_top"] and config["roi_top"] + 0.1 <= config["roi_bottom"] <= 1):
        raise ValueError("need 0 <= roi_top < roi_bottom <= 1, at least 0.1 apart")
    if not 0 < config["min_width"] < config["max_width"] <= 1:
        raise ValueError("need 0 < min_width < max_width <= 1")
    if not 0.1 <= config["scale"] <= 1 or not 0 <= config["min_confidence"] <= 1:
        raise ValueError("need 0.1 <= scale <= 1 and 0 <= min_confidence <= 1")
    if not 0 < config["smoothing"] <= 1:
        raise ValueError("need 0 < smoothing <= 1")
    if not 0 < config["max_jump"] <= 2:
        raise ValueError("need 0 < max_jump <= 2")
    if not 0 < config["max_frame_age_s"] <= 1:
        raise ValueError("need 0 < max_frame_age_s <= 1")
    # Below about 3.4 Hz the wait between frames would delay the "no frame" report
    # (max_frame_age_s + 0.1 s report interval in run.py).
    min_fps = 1 / (config["max_frame_age_s"] + 0.1)
    if type(config["max_fps"]) not in (int, float) or not min_fps <= config["max_fps"] <= 60:
        raise ValueError(f"need {min_fps:.1f} <= max_fps <= 60")
    for name, color in config["colors"].items():
        low, high, contrast = color["hsv_low"], color["hsv_high"], color["contrast"]
        for bounds in (low, high):
            if (not isinstance(bounds, list) or len(bounds) != 3
                    or any(type(x) is not int or not 0 <= x <= top
                           for x, top in zip(bounds, (179, 255, 255)))):
                raise ValueError(f"{name}: hsv must be 3 integers within 179, 255, 255")
        if any(x > y for x, y in zip(low, high)):
            raise ValueError(f"{name}: hsv_low must not exceed hsv_high")
        if type(contrast) is not int or not -200 <= contrast <= 200:
            raise ValueError(f"{name}: contrast must be an integer within -200..200")
    return config


def color_mask(roi: np.ndarray, config: dict) -> np.ndarray:
    color = config["colors"][config["color"]]
    hsv = cv2.cvtColor(cv2.GaussianBlur(roi, (5, 5), 0), cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(color["hsv_low"]), np.array(color["hsv_high"]))
    contrast = color["contrast"]
    if contrast:
        value = hsv[:, :, 2].astype(np.int16)
        width = roi.shape[1]
        # A line is at most max_width wide, so both of these points lie outside it.
        reach = min(width - 1, max(2, round(width * config["max_width"])))
        padded = cv2.copyMakeBorder(value, 0, 0, reach, reach, cv2.BORDER_REPLICATE)
        sign = 1 if contrast > 0 else -1
        for neighbour in (padded[:, :width], padded[:, 2 * reach:]):
            mask[(value - neighbour) * sign < abs(contrast)] = 0
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))


def _measure(component: np.ndarray, config: dict):
    """Return (offset, angle, confidence, slope, intercept, line width px), or None."""
    height, width = component.shape
    counts = component.sum(axis=1)
    valid = (counts >= config["min_width"] * width) & (counts <= config["max_width"] * width)
    rows = np.flatnonzero(valid)
    if len(rows) < MIN_ROWS:
        return None
    centers = (component[rows] @ np.arange(width)) / counts[rows]
    slope, intercept = np.polyfit(rows, centers, 1)
    # On a curve the whole-line fit is wrong near the car: use only the nearest rows.
    near = rows >= height * 0.75
    if near.sum() >= MIN_ROWS:
        near_slope, near_intercept = np.polyfit(rows[near], centers[near], 1)
        bottom_x = near_slope * (height - 1) + near_intercept
    else:
        bottom_x = slope * (height - 1) + intercept
    offset = float(np.clip((bottom_x - (width - 1) / 2) / ((width - 1) / 2), -1, 1))
    angle = math.degrees(math.atan(-slope))  # Going ahead is going up the image.
    curve = np.polyval(np.polyfit(rows, centers, 2), rows)
    residual = float(np.sqrt(np.mean((curve - centers) ** 2)))
    smoothness = max(0.0, 1.0 - residual / (0.1 * width))
    # Tape has an even (or evenly tapering) width; glare bulges in the middle.
    widths = counts[rows].astype(float)
    bulge = np.polyval(np.polyfit(rows, widths, 1), rows) - widths
    evenness = max(0.0, 1.0 - 2.5 * float(np.sqrt(np.mean(bulge ** 2))) / float(np.median(widths)))
    return (offset, angle, len(rows) / height * smoothness * evenness,
            slope, intercept, float(np.median(counts[rows])))


def _join_pieces(component: np.ndarray, mask: np.ndarray, measured) -> np.ndarray:
    """Add pieces on the same straight line, split off by a stripe, shadow, or gap."""
    height, width = mask.shape
    _, _, _, slope, intercept, line_px = measured
    predicted = slope * np.arange(height)[:, None] + intercept
    near = np.abs(np.arange(width)[None, :] - predicted) <= line_px
    return (component | (near & (mask > 0))).astype(np.int32)


def detect(image: np.ndarray, config: dict, previous_offset: float | None = None) -> LineResult:
    """With several lines, follow the one nearest previous_offset (or the center)."""
    height = image.shape[0]
    roi = image[int(height * config["roi_top"]):int(height * config["roi_bottom"])]
    if config["scale"] < 1:  # Same factor on both axes, so angles are unchanged.
        roi = cv2.resize(roi, None, fx=config["scale"], fy=config["scale"],
                         interpolation=cv2.INTER_AREA)
    mask = color_mask(roi, config)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    found, best_confidence = [], 0.0
    # Only the few largest blobs matter; noise must not slow the loop down.
    for label in np.argsort(stats[1:, cv2.CC_STAT_AREA])[::-1][:5] + 1 if count > 1 else ():
        component = labels == label
        measured = _measure(component.astype(np.int32), config)
        if measured:
            joined = _measure(_join_pieces(component, mask, measured), config)
            if joined and joined[2] > measured[2]:
                measured = joined
        if measured is None:
            continue
        best_confidence = max(best_confidence, measured[2])
        # Pieces of one broken line give the same answer: keep the best of them.
        same = next((i for i, other in enumerate(found) if abs(other[0] - measured[0]) < 0.1), None)
        if measured[2] < config["min_confidence"]:
            continue
        if same is None:
            found.append(measured)
        elif measured[2] > found[same][2]:
            found[same] = measured
    if not found:
        return LineResult(False, None, None, round(best_confidence, 3))
    target = 0.0 if previous_offset is None else previous_offset
    offset, angle, confidence = min(found, key=lambda m: abs(m[0] - target))[:3]
    if previous_offset is not None and abs(offset - previous_offset) > config["max_jump"]:
        return LineResult(False, None, None, round(confidence, 3), len(found))
    return LineResult(True, round(offset, 4), round(angle, 2), round(confidence, 3), len(found))
