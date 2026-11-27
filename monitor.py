"""Print the latest line, LiDAR, and fire values twice a second (Ctrl+C to stop)."""

import time

from common.valuebus import read_value

try:
    while True:
        for name, max_age_s in (("line", 0.2), ("lidar", 0.8), ("fire", 1.0)):
            print(name, read_value(name, max_age_s) or "값 없음")
        time.sleep(0.5)
except KeyboardInterrupt:
    print()
