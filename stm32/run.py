"""STM32 link process: new line / LiDAR / fire packets -> STM32 over USB serial (Nucleo ST-LINK).

The STM32 decides how to drive; this process only forwards packets (docs/stm32_link.md).
It never exits because the board is missing: it keeps retrying the port, so the other
processes are not stopped by main.py. Text the STM32 prints is shown here with [stm32].

usage: stm32/run.py [--port DEV] [--show SECONDS]
  --show 1   every second send "P" so the STM32 prints the packets it received (for testing)
"""

from __future__ import annotations

import argparse
import glob
import signal
import sys
import time
import tomllib
from pathlib import Path

import serial

from common.valuebus import DEFAULT_FOLDER
from link import PacketPicker

CONFIG_PATH = Path(__file__).resolve().parent / "config.toml"
RETRY_S = 1.0
STATS_S = 10.0
POLL_S = 0.005  # Line packets come at 15 Hz; checking every 5 ms adds at most 5 ms of delay.


def load_config(path: Path = CONFIG_PATH) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def find_port(setting: str) -> str | None:
    """"auto": the Nucleo's ST-LINK by its stable name, else the first ttyACM."""
    if setting != "auto":
        return setting
    for pattern in ("/dev/serial/by-id/*STLink*", "/dev/serial/by-id/*STM32*", "/dev/ttyACM*"):
        found = sorted(glob.glob(pattern))
        if found:
            return found[0]
    return None


class Console:
    """Print what the STM32 sends, one line at a time."""

    def __init__(self) -> None:
        self.buffer = b""

    def feed(self, data: bytes) -> None:
        self.buffer += data
        *lines, self.buffer = self.buffer.replace(b"\r", b"").split(b"\n")
        for line in lines:
            text = line.decode("utf-8", errors="replace").strip()
            if text and text != ">":
                print(f"[stm32] {text}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", help="serial device (default: config.toml port)")
    parser.add_argument("--show", type=float, default=0.0, help="send P every SECONDS (0 = off)")
    args = parser.parse_args()
    config = load_config()
    stopping = False

    def request_stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    picker = PacketPicker(DEFAULT_FOLDER, config["sources"], config["max_delay_ms"])
    console = Console()
    port = None
    next_try = next_stats = next_show = time.monotonic()
    warned = False
    while not stopping:
        now = time.monotonic()
        if port is None:
            if now < next_try:
                time.sleep(POLL_S)
                continue
            next_try = now + RETRY_S
            device = find_port(args.port or config["port"])
            try:
                if device is None:
                    raise serial.SerialException("no STM32 serial device")
                port = serial.Serial(device, config["baud"], timeout=0, write_timeout=0.1)
            except serial.SerialException as error:
                if not warned:
                    print(f"[stm32] waiting for the board: {error}", file=sys.stderr)
                    warned = True
                continue
            print(f"[stm32] connected {device} {config['baud']} bps", file=sys.stderr)
            warned = False
            picker.poll()  # Skip what piled up while disconnected: send only new packets.
            continue
        try:
            for packet in picker.poll():
                port.write(packet)
            if args.show and now >= next_show:
                next_show = now + args.show
                port.write(b"P\r\n")
            waiting = port.in_waiting
            if waiting:
                console.feed(port.read(waiting))
        except (serial.SerialException, OSError) as error:  # Unplugged: retry, keep the rest running.
            print(f"[stm32] lost the port: {error}", file=sys.stderr)
            port.close()
            port = None
            continue
        if now >= next_stats:
            next_stats = now + STATS_S
            print(f"[stm32] {picker.stats.text()}", file=sys.stderr)
        time.sleep(POLL_S)
    if port is not None:
        port.close()
    print(f"[stm32] stopped: {picker.stats.text()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
