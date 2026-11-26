# 설치·연결·실행

## 1. 설치 (처음 한 번)

Raspberry Pi OS (64비트, Python 3.13). picamera2·libcamera·numpy·OpenCV는 OS 패키지를 쓰므로
가상환경을 `--system-site-packages`로 만든다.

```bash
sudo apt install -y python3-picamera2 python3-opencv   # 보통 이미 설치돼 있음
cd /home/song/proj
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt               # pyserial, websockets
```

사용자는 `dialout`(시리얼), `video`(카메라) 그룹에 들어 있어야 한다: `id` 로 확인.

## 2. 하드웨어 연결과 OS 설정 변경 내역

### 카메라
- CSI 카메라 (OV5647). `/boot/firmware/config.txt`의 `camera_auto_detect=1`로 자동 인식.
- 확인: `rpicam-hello --list-cameras`
- 거꾸로 달려 있어 `camera/config.toml`의 `rotate_180 = true`.

### LiDAR (GPIO UART)
- LiDAR **TX → Pi 핀 10 (GPIO15, UART RX)**, GND → Pi GND. Pi에서 LiDAR로 보내는 것은 없다.
- 115200bps 8-N-1. 장치 이름 `/dev/serial0` (→ `ttyS0`). `lidar/config.toml`의 `port`.
- **LiDAR TX 전압은 아직 확인 안 했다.** Pi GPIO는 3.3V 전용이다. 5V 신호면 레벨 변환기를 넣어야 한다.
- USB-UART 변환기를 쓰면 `port = "/dev/ttyUSB0"`로 바꾼다.

이를 위해 2026-11-26에 OS 설정을 바꿨다 (재부팅 필요했음):

| 파일 | 변경 | 백업 |
|---|---|---|
| `/boot/firmware/config.txt` | 맨 아래에 `enable_uart=1` 추가 | `config.txt.bak-uart` |
| `/boot/firmware/cmdline.txt` | `console=serial0,115200` 제거 (UART를 리눅스 콘솔이 쓰지 않게) | `cmdline.txt.bak-uart` |

되돌리려면 백업 파일을 원래 이름으로 복사하고 재부팅한다.

### STM32 (아직 연결 안 함)
나중에 연결할 때: Pi GPIO UART는 3.3V 논리. STM32와 GND를 공유하고 TX↔RX를 엇갈려 연결한다.
GPIO UART는 LiDAR가 쓰고 있으므로 STM32는 USB(가상 COM, `/dev/ttyACM0`)나 다른 UART를 쓴다.

### Wi-Fi
Pi는 Wi-Fi(wlan0)에 연결되어 있다. 스트리밍은 Wi-Fi가 끊겨도 선·LiDAR에 영향을 주지 않고 스스로 다시 연결한다.
Pi 주소 확인: `hostname -I`

## 3. 실행

```bash
cd /home/song/proj
.venv/bin/python main.py                       # 전부 (camera, line, lidar, fire, stream)
.venv/bin/python main.py --no-stream           # 스트리밍 빼고 (--no-fire: 불 감지 빼고)
.venv/bin/python main.py --lidar-replay lidar/captures/COM5_2026-11-16.hex   # LiDAR 센서 없이 저장 데이터로
```

Ctrl+C로 멈추면 모든 프로세스가 함께 멈춘다. 서비스로 이미 돌고 있으면 카메라가 이미 열려 있어서 실패하니
먼저 `sudo systemctl stop firecar`.

`main.py` 동작:
- 프로세스가 죽으면 2초 뒤 다시 띄운다.
- camera·line·lidar 중 하나가 60초 안에 5번 죽으면 전부 멈추고 코드 1로 끝난다 (systemd가 전체를 다시 시작).
- fire·stream은 계속 죽어도 다른 프로세스를 멈추지 않고 30초 뒤 다시 띄운다.

### 값 보기 (다른 터미널에서)

```bash
PYTHONPATH=. .venv/bin/python monitor.py                          # 선·LiDAR·불 값 0.5초마다
PYTHONPATH=. .venv/bin/python camera/snapshot.py /tmp/cam.jpg     # 지금 화면 저장 (카메라를 새로 열지 않음)
cd line && PYTHONPATH=.:.. ../.venv/bin/python preview.py /tmp/line.jpg   # 선 인식 결과를 그린 사진
cat /dev/shm/firecar/lidar.json                                   # 원본 값
```

### 스트리밍 화면 보기 (가상 웹앱)

실제 웹앱이 없을 때 시험용 서버로 화면을 본다. Pi에서 돌려도 되고 PC에서 돌려도 된다.

```bash
.venv/bin/python stream/dev_server.py          # 포트 8090
```

- Pi에서 돌릴 때: `stream/config.toml`의 기본값 `server_url = "ws://127.0.0.1:8090/ingest"` 그대로.
  같은 Wi-Fi의 PC·휴대폰 브라우저로 `http://<Pi 주소>:8090/` 접속.
- PC에서 돌릴 때: PC에 `pip install websockets` 후 실행하고, Pi의 `server_url`을 `ws://<PC 주소>:8090/ingest`로 바꾼다.
- 화면 위에 서버·차·카메라 연결 상태와 fps가 나온다.

실제 웹앱이 생기면 `stream/config.toml`의 `server_url`(필요하면 `token`)만 바꾼다. 웹앱 담당자에게는 [stream.md](stream.md)를 준다.

## 4. 전원 켜면 자동 실행

`deploy/firecar.service`가 부팅 때 `main.py`를 띄운다. 설치 (sudo 암호 필요):

```bash
sudo cp /home/song/proj/deploy/firecar.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now firecar
```

| 하고 싶은 것 | 명령 |
|---|---|
| 상태 보기 | `systemctl status firecar` |
| 로그 보기 | `journalctl -u firecar -f` |
| 멈추기 (직접 실행해 볼 때) | `sudo systemctl stop firecar` |
| 다시 시작 (설정 바꾼 뒤) | `sudo systemctl restart firecar` |
| 자동 실행 끄기 | `sudo systemctl disable --now firecar` |

`config.toml`을 바꾸면 다시 시작해야 반영된다.

`lidar/deploy/lidar-bridge.service.example`은 쓰지 않는 예전 `lidar_bridge.py`용이다. 설치하지 않는다.
