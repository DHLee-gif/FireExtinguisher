"""PC에서 Raspberry Pi인 척 STM32(firecar)로 센서 패킷을 보내는 시험 프로그램.

Pi 없이 STM32 수신 코드를 시험하려고 만든 것. 패킷 형식은 Pi 코드와 같다
(docs/line_packet.md, docs/lidar_packet.md, docs/fire.md).

  선 v2 (C3 4C, 25B)      15Hz  치우침이 -800 ~ +800으로 천천히 왔다 갔다
  LiDAR 요약 (C3 5C, 21B)  5Hz   앞 거리가 1000mm → 150mm로 줄었다가 다시 처음부터
  불 v1 (C3 6C, 22B)       2Hz   NO_FIRE → SUSPECT → FIRE 반복

1초마다 "P"를 보내 STM32가 받은 값을 출력하게 하고, 그 답을 화면에 보여 준다.
마지막 2초는 패킷을 끊고 "?"를 보내서 Pi 연결 끊김(LOST)이 보이는지 확인한다.

설치:  pip install pyserial
실행:  python fake_pi.py COM5            (포트 번호는 장치 관리자 → 포트(COM & LPT)에서 확인)
       python fake_pi.py COM5 --seconds 20
주의:  CubeIDE 터미널이 같은 COM 포트를 열고 있으면 실행이 안 된다. 먼저 터미널을 닫는다.
"""

import argparse
import math
import struct
import sys
import threading
import time

import serial


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def with_crc(body: bytes) -> bytes:
    return body + struct.pack("<H", crc16_ccitt_false(body))


def line_packet(seq: int, t: float) -> bytes:
    offset = round(800 * math.sin(t * 0.5))          # -800 ~ +800
    return with_crc(b"\xC3\x4C" + struct.pack(
        "<BBHhhhhhBBbHH", 2, 0, seq & 0xFFFF,
        offset, 250, offset, 250, 0, 90, 1, -1 if offset < 0 else 1, 0, 40))


def summary_packet(seq: int, t: float) -> bytes:
    front = 1000 - round((t % 5.0) / 5.0 * 850)      # 1000 → 150mm, 5초마다 반복
    return with_crc(b"\xC3\x5C" + struct.pack(
        "<BBHHHHHhBH", 1, 0, seq & 0xFFFF,
        front, 0xFFFE, 400, min(front, 400), 0, 0, 150))


def fire_packet(seq: int, t: float) -> bytes:
    phase = int(t) % 6                                # 0~1 NO_FIRE, 2~3 SUSPECT, 4~5 FIRE
    if phase < 2:
        return with_crc(b"\xC3\x6C" + struct.pack(
            "<BBHhHHBBBBHH", 1, 1, seq & 0xFFFF, 0x7FFF, 0xFFFF, 0xFFFF, 0, 0, 5, 0, 0xFFFF, 300))
    status, hits = (2, 2) if phase < 4 else (0, 4)
    return with_crc(b"\xC3\x6C" + struct.pack(
        "<BBHhHHBBBBHH", 1, status, seq & 0xFFFF, 300, 700, 25, 85, hits, 5, 1, 0, 300))


def reader(port: serial.Serial, stop: threading.Event) -> None:
    while not stop.is_set():
        data = port.read(256)
        if data:
            sys.stdout.write(data.decode("utf-8", errors="replace"))
            sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("port", help="STM32 COM 포트, 예: COM5")
    parser.add_argument("--seconds", type=float, default=10.0, help="패킷을 보낼 시간 (기본 10초)")
    args = parser.parse_args()

    port = serial.Serial(args.port, 115200, timeout=0.05)
    stop = threading.Event()
    threading.Thread(target=reader, args=(port, stop), daemon=True).start()

    periods = {"line": 1 / 15, "sum": 1 / 5.2, "fire": 1 / 2, "show": 1.0}
    builders = {"line": line_packet, "sum": summary_packet, "fire": fire_packet}
    seq = dict.fromkeys(builders, 0)
    start = time.monotonic()
    next_at = dict.fromkeys(periods, start)
    try:
        while (now := time.monotonic()) - start < args.seconds:
            t = now - start
            for name, build in builders.items():
                if now >= next_at[name]:
                    port.write(build(seq[name], t))
                    seq[name] += 1
                    next_at[name] += periods[name]
            if now >= next_at["show"]:
                print(f"\n----- {t:4.1f}s: P -----")
                port.write(b"P\r\n")
                next_at["show"] += periods["show"]
            time.sleep(0.002)

        print("\n----- 패킷 중단: 0.3초 뒤 ? (아직 OK), 1.5초 뒤 ? (LOST가 나와야 함) -----")
        time.sleep(0.3)
        port.write(b"?\r\n")
        time.sleep(1.2)
        port.write(b"?\r\n")
        time.sleep(0.5)
    finally:
        stop.set()
        time.sleep(0.1)
        port.close()
    print(f"\n보낸 패킷: line {seq['line']}, sum {seq['sum']}, fire {seq['fire']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
