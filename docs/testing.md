# 테스트와 점검 절차

## 1. 자동 테스트 + 규칙 검사 (장치 없이)

코드를 고친 뒤에는 항상 돌린다.

```bash
cd /home/song/proj
.venv/bin/python tools/check.py            # 전부
.venv/bin/python tools/check.py stream     # 한 영역만
```

하는 일:
- 각 영역의 `tests/test_*.py`와 `main.py` 테스트(`tests/test_main.py`) 실행
- 규칙 검사: 영역끼리 import 금지, `picamera2`는 `camera/`만, `serial`은 `lidar/`·`stm32/`만,
  `except:`·`except Exception: pass` 금지

`common/`을 바꾸면 모든 영역이 영향을 받으니 전부 돌린다. 영역 하나만 직접 돌리려면:

```bash
cd /home/song/proj/lidar && PYTHONPATH=.:.. ../.venv/bin/python -m unittest discover -s tests
```

테스트가 통과했다고 실제 환경에서 된다는 뜻은 아니다. 실제 장치로 확인하지 않았으면 "미확인"이라고 적는다.

2026-11-26 결과: camera 5, line 30, lidar 27, fire 16, stream 10, common 9, main 3개 모두 통과.

## 2. Pi 상태 점검

```bash
vcgencmd measure_temp; vcgencmd get_throttled; uptime; free -m
ls -l /dev/serial0 /dev/serial/by-id /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
pgrep -af '/home/song/proj'
ls -l /dev/shm/firecar
```

`throttled=0x0`이 아니면 저전압·과열 기록이 있는 것이다 (전원 어댑터·배터리 확인).

## 3. 카메라 점검

1. 촬영 프로세스가 켜져 있는지: `pgrep -af camera/capture.py`
2. 켜져 있으면 카메라를 새로 열지 말고 공유 영상을 저장한다:
   `PYTHONPATH=. .venv/bin/python camera/snapshot.py /tmp/cam.jpg`
   (꺼져 있으면 먼저 `PYTHONPATH=. timeout 8 .venv/bin/python camera/capture.py &`)
3. 저장한 사진을 **눈으로 본다.** 출력되는 밝기(mean)·선명도(sharp) 숫자만으로 정상이라고 하지 않는다.
4. 인식이 안 되면 `rpicam-hello --list-cameras`와 `/boot/firmware/config.txt`의 카메라 줄을 확인한다.
5. 노출은 `camera/config.toml`에서만 조정한다.

## 4. LiDAR 검증 (해석 코드나 패킷을 바꾼 뒤)

기준은 [lidar_packet.md](lidar_packet.md)다. 코드가 아니라 문서의 규격으로 기대값을 직접 계산해 비교한다.

1. `lidar/tests` 실행
2. `lidar/captures/*.hex`를 재생해서 정상/손상 프레임 수, 회전 Hz, 구역별 거리 확인
   (`main.py --lidar-replay ...` 후 `monitor.py`)
3. 패킷: 69바이트, 버전 3, CRC-16/CCITT-FALSE, 오프셋, little-endian
4. 경계값: 구역 경계각, 120/8000mm, 0, invalid bit, 각도 wrap, sequence wrap
5. 오래된 값이나 없는 값이 정상 거리로 나가지 않는지
6. 실제 센서: 물체를 정면·오른쪽·왼쪽에 두고 해당 구역에 나오는지, 줄자 거리와 맞는지

## 5. 선·불 검증 (`line/`, `fire/`를 바꾼 뒤)

1. 해당 영역 테스트 실행
2. 정답을 아는 합성 영상(`line/tests/synthetic.py`)과 실제 사진으로 비교한다. 실제 사진은 눈으로 본다.
3. 선: 좌우 부호(선이 화면 오른쪽이면 +), 중앙=0, 각도 부호, 선 없음, 밝은 바닥·반사
4. 불: 작은 불꽃, 전등·햇빛·주황색 물체 오탐, "불 없음"과 "값 없음" 구분. 절차는 [fire.md](fire.md) "실제 시험"
5. 오래된 영상이 현재 값으로 나가지 않는지

선 인식 결과를 그림으로 보기:
```bash
cd line && PYTHONPATH=.:.. ../.venv/bin/python preview.py /tmp/line.jpg          # 지금 카메라 화면
cd line && PYTHONPATH=.:.. ../.venv/bin/python preview.py /tmp/line.jpg in.jpg   # 저장된 사진
```
파란색이 선 색으로 잡힌 부분, 노란 사각형이 보는 영역이다.

## 6. 고장 격리 시험 (5단계)

"하나가 죽어도 나머지는 산다"를 실제로 확인한다. `main.py`를 띄우고 다른 터미널에서:

| 시험 | 방법 | 기대 |
|---|---|---|
| 스트리밍 서버 끊김 | `dev_server.py` 종료 | stream은 재연결 시도, `monitor.py`에 선·LiDAR 계속 나옴 → **2026-11-26 확인** |
| 스트림 프로세스 죽음 | `pkill -f stream/run.py` | 2초 뒤 다시 뜸, 선·LiDAR 계속 |
| 선 프로세스 죽음 | `pkill -f line/run.py` | 다시 뜸, LiDAR·스트림 계속 |
| LiDAR 선 뽑기 | UART 선 분리 | lidar는 `NO_DATA`, 다시 꽂으면 회복, 선·스트림 계속 |
| 카메라 프로세스 죽음 | `pkill -f camera/capture.py` | 선은 "영상 없음(2)", 스트림은 `no_frame`, LiDAR 계속, 다시 뜨면 회복 |
| 불 감지 죽음 | `pkill -f fire/run.py` | 다시 뜸, 나머지 계속. 모델 없으면 `NO_MODEL`만 나오고 죽지 않음 → **2026-11-26 확인** |

불 감지가 붙은 뒤 전체를 다시 한다.
