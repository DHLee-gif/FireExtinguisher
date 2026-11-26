"""Save the shared frame to an image file without opening the camera."""

import sys

import cv2

from common.framebus import read_frame


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: snapshot.py OUTPUT.jpg", file=sys.stderr)
        return 2
    frame = read_frame(max_age_s=1.0)
    if frame is None:
        print("no recent frame; is camera/capture.py running?", file=sys.stderr)
        return 1
    if not cv2.imwrite(sys.argv[1], frame.image):
        print(f"cannot write {sys.argv[1]}", file=sys.stderr)
        return 1
    gray = cv2.cvtColor(frame.image, cv2.COLOR_BGR2GRAY)
    print(f"seq={frame.sequence} age={frame.age_s() * 1000:.0f}ms "
          f"mean={gray.mean():.0f} sharp={cv2.Laplacian(gray, cv2.CV_64F).var():.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
