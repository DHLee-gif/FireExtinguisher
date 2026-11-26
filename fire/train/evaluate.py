"""Picture-level check of a fire ONNX model on the test split, with the same code the Pi runs.

usage (project venv, from fire/): PYTHONPATH=.:.. ../.venv/bin/python train/evaluate.py MODEL.onnx
         [--size 320] [--fire-class 1] [--threshold 0.25] [--data ~/fire-train/dfire]
Reports: share of fire pictures with at least one fire box, share of no-fire pictures with a
false box, and the median inference time on one thread. Run it on core 3 (taskset -c 3 nice -n 19)
while the car service runs.
"""

import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from detector import detect, load_config, load_model  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("model", type=Path)
    parser.add_argument("--size", type=int, default=320)
    parser.add_argument("--fire-class", type=int, default=1)
    parser.add_argument("--threshold", type=float, default=0.25)
    parser.add_argument("--data", type=Path, default=Path.home() / "fire-train" / "dfire")
    args = parser.parse_args()
    cv2.setNumThreads(1)
    config = {**load_config(), "input_size": args.size, "fire_class": args.fire_class,
              "score_threshold": args.threshold}
    net = load_model(args.model)
    found = missed = false_alarm = clean = 0
    times = []
    for image_path in sorted((args.data / "images" / "test").glob("*.jpg")):
        has_fire = (args.data / "labels" / "test" / f"{image_path.stem}.txt").read_text().strip() != ""
        image = cv2.imread(str(image_path))
        start = time.perf_counter()
        boxes = detect(net, image, config)
        times.append(time.perf_counter() - start)
        if has_fire:
            found, missed = found + bool(boxes), missed + (not boxes)
        else:
            false_alarm, clean = false_alarm + bool(boxes), clean + (not boxes)
    times.sort()
    print(f"size {args.size} threshold {args.threshold}: fire found {found}/{found + missed} "
          f"({found / max(1, found + missed):.0%}), false alarms {false_alarm}/{false_alarm + clean} "
          f"({false_alarm / max(1, false_alarm + clean):.0%}), median {times[len(times) // 2] * 1000:.0f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
