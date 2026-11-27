"""YOLO (ultralytics v8/11 ONNX export) fire detector run with OpenCV DNN. No PyTorch on the Pi."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

CONFIG_PATH = Path(__file__).with_name("config.toml")
PAD_VALUE = 114  # Gray border, the same as ultralytics letterbox.


@dataclass(frozen=True)
class Detection:
    x: float      # Box center, -1 left edge .. 0 center .. +1 right edge
    y: float      # Box center, 0 top .. 1 bottom (lower in the picture = usually closer)
    width: float  # Box size as a fraction of the picture
    height: float
    score: float  # 0..1


def load_config(path: Path = CONFIG_PATH) -> dict:
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    for key in ("input_size", "window", "confirm_hits", "max_fps", "threads", "max_frame_age_s"):
        if config[key] <= 0:
            raise ValueError(f"{key} must be positive")
    if config["input_size"] % 32:
        raise ValueError("input_size must be a multiple of 32")
    if not 1 <= config["confirm_hits"] <= config["window"] <= 255:
        raise ValueError("need 1 <= confirm_hits <= window <= 255")
    for key in ("score_threshold", "nms_threshold"):
        if not 0 < config[key] < 1:
            raise ValueError(f"{key} must be between 0 and 1")
    if config["fire_class"] < 0:
        raise ValueError("fire_class must be >= 0")
    return config


def model_file(config: dict) -> Path:
    path = Path(config["model_path"])
    return path if path.is_absolute() else Path(__file__).parent / path


def load_model(path: Path):
    """Raise FileNotFoundError when missing, cv2.error when the file is not a usable model."""
    if not path.is_file():
        raise FileNotFoundError(path)
    return cv2.dnn.readNetFromONNX(str(path))


def letterbox(image: np.ndarray, size: int) -> tuple[np.ndarray, float, int, int]:
    """Fit into size x size keeping the shape. Return the blob input, scale, and left/top padding."""
    height, width = image.shape[:2]
    scale = min(size / width, size / height)
    new_w, new_h = round(width * scale), round(height * scale)
    left, top = (size - new_w) // 2, (size - new_h) // 2
    canvas = np.full((size, size, 3), PAD_VALUE, np.uint8)
    canvas[top:top + new_h, left:left + new_w] = cv2.resize(image, (new_w, new_h),
                                                            interpolation=cv2.INTER_LINEAR)
    return canvas, scale, left, top


def decode(output: np.ndarray, config: dict, scale: float, left: int, top: int,
           image_w: int, image_h: int) -> list[Detection]:
    """ultralytics output (1, 4 + classes, boxes) -> fire detections, best first."""
    rows = np.squeeze(output, 0)
    if rows.ndim != 2:
        raise ValueError(f"unexpected model output shape {output.shape}")
    # Always (4 + classes, boxes) for ultralytics exports; guessing a transposed layout
    # from the shape would be wrong when few boxes come out.
    classes = rows.shape[0] - 4
    if config["fire_class"] >= classes:
        raise ValueError(f"fire_class {config['fire_class']} but model has {classes} classes")
    scores = rows[4 + config["fire_class"]]
    keep = np.flatnonzero(scores >= config["score_threshold"])
    if keep.size == 0:
        return []
    cx, cy, w, h = rows[0, keep], rows[1, keep], rows[2, keep], rows[3, keep]
    # Back from the padded model input to the original picture.
    x1, y1 = (cx - w / 2 - left) / scale, (cy - h / 2 - top) / scale
    bw, bh = w / scale, h / scale
    boxes = [[float(a), float(b), float(c), float(d)] for a, b, c, d in zip(x1, y1, bw, bh)]
    chosen = cv2.dnn.NMSBoxes(boxes, scores[keep].astype(float).tolist(),
                              config["score_threshold"], config["nms_threshold"])
    detections = []
    for index in np.array(chosen).reshape(-1):
        x, y, bw_, bh_ = boxes[index]
        x0, y0 = max(0.0, x), max(0.0, y)
        x1_, y1_ = min(float(image_w), x + bw_), min(float(image_h), y + bh_)
        if x1_ <= x0 or y1_ <= y0:
            continue
        center_x, center_y = (x0 + x1_) / 2, (y0 + y1_) / 2
        detections.append(Detection(
            x=round(center_x / image_w * 2 - 1, 4), y=round(center_y / image_h, 4),
            width=round((x1_ - x0) / image_w, 4), height=round((y1_ - y0) / image_h, 4),
            score=round(float(scores[keep][index]), 3)))
    return sorted(detections, key=lambda d: d.score, reverse=True)


def detect(net, image: np.ndarray, config: dict) -> list[Detection]:
    size = config["input_size"]
    canvas, scale, left, top = letterbox(image, size)
    # BGR -> RGB, 0..1, NCHW: what ultralytics models expect.
    blob = cv2.dnn.blobFromImage(canvas, 1 / 255.0, (size, size), swapRB=True, crop=False)
    net.setInput(blob)
    output = net.forward()
    return decode(output, config, scale, left, top, image.shape[1], image.shape[0])
