# 소방 RC카 — Raspberry Pi 쪽

Raspberry Pi 4가 LiDAR 거리, 선 위치, (예정) 불 위치를 STM32용 패킷으로 만들고, 카메라 화면을 Wi-Fi로 웹앱에 보낸다.
주행 판단과 모터 제어는 STM32가 한다.

**문서는 [`docs/`](docs/README.md)에 있다. 처음이면 [`docs/status.md`](docs/status.md)부터 읽는다.**

```bash
.venv/bin/python main.py          # 전부 실행 (camera, line, lidar, stream)
.venv/bin/python tools/check.py   # 규칙 검사 + 전체 테스트 (장치 없이)
```
