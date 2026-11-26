"""Save an image with the mask and detected line drawn on it.

usage: preview.py OUTPUT.jpg [INPUT.jpg]   (without INPUT: the shared camera frame)
"""

import math
import sys

import cv2
import numpy as np

from common.framebus import read_frame
from detector import color_mask, detect, load_config


def draw(image, config):
    height, width = image.shape[:2]
    top, bottom = int(height * config["roi_top"]), int(height * config["roi_bottom"])
    output = image.copy()
    region = output[top:bottom]
    # Same scaling as detect(), so the picture shows the mask really used.
    small = cv2.resize(np.ascontiguousarray(image[top:bottom]), None, fx=config["scale"],
                       fy=config["scale"], interpolation=cv2.INTER_AREA)
    mask = cv2.resize(color_mask(small, config), (width, bottom - top), interpolation=cv2.INTER_NEAREST)
    region[mask > 0] = (255, 160, 0)
    cv2.rectangle(output, (0, top), (width - 1, bottom - 1), (0, 255, 255), 1)
    result = detect(image, config)
    text = f"NO LINE c={result.confidence:.2f}"
    if result.found:
        x = (width - 1) / 2 * (1 + result.offset)
        ahead = x + math.tan(math.radians(result.angle_deg)) * (bottom - top)
        cv2.line(output, (round(x), bottom - 1), (round(ahead), top), (0, 0, 255), 2)
        text = f"offset={result.offset:+.2f} angle={result.angle_deg:+.0f} c={result.confidence:.2f}"
    cv2.putText(output, text, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    return output, result


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    if len(sys.argv) == 3:
        image = cv2.imread(sys.argv[2])
    else:
        frame = read_frame(max_age_s=1.0)
        image = None if frame is None else frame.image
    if image is None:
        print("no input image", file=sys.stderr)
        return 1
    output, result = draw(image, load_config())
    if not cv2.imwrite(sys.argv[1], output):
        print(f"cannot write {sys.argv[1]}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
