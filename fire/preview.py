"""Save a picture with the fire boxes drawn on it (to check a trained model by eye).

usage: preview.py OUTPUT.jpg [INPUT.jpg]   (without INPUT: the shared camera frame)
"""

import sys

import cv2

from common.framebus import read_frame
from detector import detect, load_config, load_model, model_file


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    config = load_config()
    if len(sys.argv) == 3:
        image = cv2.imread(sys.argv[2])
        if image is None:
            print(f"cannot read {sys.argv[2]}", file=sys.stderr)
            return 1
    else:
        frame = read_frame(max_age_s=1.0)
        if frame is None:
            print("no recent frame; is camera/capture.py running?", file=sys.stderr)
            return 1
        image = frame.image.copy()
    try:
        net = load_model(model_file(config))
    except FileNotFoundError as error:
        print(f"no model: {error} (see docs/fire.md)", file=sys.stderr)
        return 1
    detections = detect(net, image, config)
    height, width = image.shape[:2]
    for d in detections:
        cx, cy = (d.x + 1) / 2 * width, d.y * height
        x0, y0 = int(cx - d.width * width / 2), int(cy - d.height * height / 2)
        x1, y1 = int(cx + d.width * width / 2), int(cy + d.height * height / 2)
        cv2.rectangle(image, (x0, y0), (x1, y1), (0, 0, 255), 2)
        cv2.putText(image, f"fire {d.score:.2f}", (x0, max(15, y0 - 5)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 0, 255), 1)
    if not cv2.imwrite(sys.argv[1], image):
        print(f"cannot write {sys.argv[1]}", file=sys.stderr)
        return 1
    print(f"{len(detections)} fire box(es): {[(d.x, d.y, d.score) for d in detections]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
