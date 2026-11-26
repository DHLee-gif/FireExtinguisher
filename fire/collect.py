"""Save camera pictures for training without opening the camera (camera/capture.py must run).

usage: collect.py FOLDER [--every 0.5] [--count 100]
  e.g. collect.py dataset/raw/candle_1m   (inside fire/)  -> 100 pictures, one every 0.5 s
Name folders by what is in them (candle_1m, lighter_dark, lamp_no_fire ...) to make labelling easier.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2

from common.framebus import read_frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--every", type=float, default=0.5, help="seconds between pictures")
    parser.add_argument("--count", type=int, default=100)
    args = parser.parse_args()
    if args.every <= 0 or args.count <= 0:
        parser.error("--every and --count must be positive")
    args.folder.mkdir(parents=True, exist_ok=True)
    saved, last_ns = 0, None
    try:
        while saved < args.count:
            frame = read_frame(max_age_s=1.0, after_ns=last_ns)
            if frame is None:
                if last_ns is None or (time.monotonic_ns() - last_ns) / 1e9 > 2:
                    print("no recent camera frame; is camera/capture.py (or main.py) running?", file=sys.stderr)
                    return 1
                time.sleep(0.01)
                continue
            last_ns = frame.captured_ns
            name = args.folder / f"{args.folder.name}_{datetime.now():%Y%m%d_%H%M%S_%f}.jpg"
            if not cv2.imwrite(str(name), frame.image, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                print(f"cannot write {name}", file=sys.stderr)
                return 1
            saved += 1
            print(f"\r{saved}/{args.count} {name.name}", end="", flush=True)
            time.sleep(args.every)
    except KeyboardInterrupt:
        pass
    print(f"\nsaved {saved} pictures in {args.folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
