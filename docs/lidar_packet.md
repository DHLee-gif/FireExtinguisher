# LiDAR 처리와 STM32 패킷 규격

> **지금 쓰는 프로그램은 `lidar/run.py`입니다** (맨 아래 "`run.py`" 절). 패킷을 만들어 공유 메모리
> `/dev/shm/firecar/lidar.json`에 두기만 하고 STM32로 보내지는 않습니다.
> 아래 앞부분에 나오는 `lidar/lidar_bridge.py`는 STM32 포트를 직접 여는 예전 프로그램이라 **쓰지 않습니다**.
> 패킷 형식(v3 69바이트, 주행 요약 21바이트)과 상태 코드 설명은 그대로 유효합니다.
> v3 패킷을 바꾸면 STM32 펌웨어도 함께 바꿔야 합니다 (펌웨어는 이 저장소에 없음).

## 역할과 데이터 흐름

```text
LiDAR UART (115200 8-N-1)
  → Raspberry Pi: 36바이트 프레임 재조립·검증·거리 상태 분류·각도/방향 변환
  → STM32 UART (기본 115200 8-N-1): 한 바퀴 요약 패킷
  → STM32가 주행 판단 및 모터 제어
```

`lidar_bridge.py`는 모터 명령을 만들지 않습니다. 스캔 사이클 결과와 데이터 건전성 정보를 전달합니다. 각 사이클이 끝날 때 한 패킷을 전송합니다. 각도 wrap이 오지 않은 채 기본 500 ms(또는 회전 주기의 2배)가 지나면 수집 중 사이클을 `PARTIAL`로 보내고 새 사이클을 시작합니다. 이후에도 센서 프레임이 없으면 0개 프레임의 partial 상태가 반복되어 센서 입력 중단을 전달합니다. 포트 연결은 최초 1회와 최대 5회 재시도(총 6회)합니다. 재시도 간격은 1, 2, 4, 8, 10초입니다. 소진하면 오류로 프로세스를 종료하며, 이후에는 systemd가 120초 동안 최대 3회까지 서비스 실행을 허용합니다. STM32도 패킷 자체의 수신 타임아웃을 두어야 합니다.

## LiDAR 입력 처리

- 고정 36바이트 `55 AA 03 08` 프레임을 UART 스트림에서 재조립합니다.
- 샘플 수와 Camsense 15비트 shift-and-fold 체크섬을 확인합니다. 손상 프레임은 조용히 정상 데이터로 취급하지 않고 사이클 오류 수에 반영합니다.
- 8개 점의 각도는 시작각부터 끝각까지 7간격으로 보간합니다. SDK 범용 경로 `+28.5°` 보정을 적용한 다음 `--forward-angle` 장착각을 빼 차량 기준 방향으로 바꿉니다.
- 거리는 `raw & 0x3FFF`, invalid flag는 bit 15로 해석합니다. 품질 바이트도 전달하지만, 의미가 확정되지 않았으므로 품질 기준으로 버리지는 않습니다.
- 구역 순서는 전방, 전방 우측, 우측, 후방 우측, 후방, 후방 좌측, 좌측, 전방 좌측입니다. 각 45도입니다.
- 구역 안에 여러 점이 있으면 가장 가까운 의미 있는 반환값을 남깁니다. 근접값과 유효 거리, 원거리 값은 각각 상태로 보존합니다.

## STM32 고정 패킷 v3

총 길이 **69바이트**. 다중 바이트 정수는 little-endian입니다. CRC-16/CCITT-FALSE는 바이트 0–66 전체에 적용되고, CRC는 low byte부터 보냅니다. STM32 수신기는 version `3`과 69바이트 길이를 확인해야 합니다.

| 오프셋 | 크기 | 필드 | 정의 |
|---:|---:|---|---|
| 0 | 2 | Header | `C3 3C` |
| 2 | 1 | Version | `3` |
| 3 | 1 | Cycle status | `0` complete, `1` partial/loss, `2` startup partial |
| 4 | 2 | Sequence | 매 사이클 증가, uint16 wrap |
| 6 | 2 | Valid frame count | 체크섬/구조가 정상인 스캔 프레임 수 |
| 8 | 2 | Bad frame count | 이 사이클에서 확인한 손상 후보 프레임 수 |
| 10 | 2 | Rotation rate | milli-Hz, 예: 5200 = 5.2 Hz |
| 12 | 2 | Scan period | ms/회전, 예: 192 ms |
| 14 | 2 | Measured cycle elapsed | 이 사이클 수집 시작부터 패킷 생성까지 경과한 ms, uint16 saturate |
| 16 | 2 | Sensor-latency speed bound | mm/s; 설정하지 않으면 `0xFFFF` (미설정) |
| 18 | 1 | Observed zone mask | bit 0–7: 해당 구역의 각도 샘플을 한 번 이상 수신했는지 표시; 1=관측됨 |
| 19 | 48 | 8 zone records | 각 6바이트: status(uint8), distance(uint16 mm), raw quality(uint8), age(uint16 ms) |
| 67 | 2 | CRC-16 | CRC-16/CCITT-FALSE, little-endian |

### 구역 인덱스와 차체 방향

STM32의 `i`번째 구역 레코드와 observed mask의 bit `i`는 아래 표의 같은 방향을 뜻합니다. 레코드 시작 오프셋은 `19 + 6 × i`입니다. 각도는 **차체 기준**이며 `0°=전방`, 양수는 차체 기준 오른쪽(시계 방향), 음수는 왼쪽입니다. `--forward-angle`로 설치각을 보정한 좌표입니다.

| i / mask bit | 구역 | 차체 기준 각도 범위 | 레코드 시작 오프셋 |
|---:|---|---|---:|
| 0 | 전방 | `−22.5° ≤ bearing < +22.5°` | 19 |
| 1 | 전방 우측 | `+22.5° ≤ bearing < +67.5°` | 25 |
| 2 | 우측 | `+67.5° ≤ bearing < +112.5°` | 31 |
| 3 | 후방 우측 | `+112.5° ≤ bearing < +157.5°` | 37 |
| 4 | 후방 | `bearing ≥ +157.5°` 또는 `bearing < −157.5°` | 43 |
| 5 | 후방 좌측 | `−157.5° ≤ bearing < −112.5°` | 49 |
| 6 | 좌측 | `−112.5° ≤ bearing < −67.5°` | 55 |
| 7 | 전방 좌측 | `−67.5° ≤ bearing < −22.5°` | 61 |

예를 들어 전방은 payload offset 19의 레코드이며 observed zone mask bit 0으로 관측 여부를 확인합니다. 후방은 offset 43, bit 4입니다. 센서 좌표의 `+28.5°` SDK 보정과 설치 후 `--forward-angle` 보정은 Pi에서 적용한 뒤 이 차체 기준 구역에 넣습니다.

### 상태 코드

구역별 측정 상태:

| 값 | 이름 | 거리 필드 |
|---:|---|---|
| 0 | `VALID` | 유효 거리(mm) |
| 1 | `TOO_CLOSE` | 실제 검출 거리(mm), 기본 하한 120 mm 미만 |
| 2 | `TOO_FAR` | 실제 검출 거리(mm), 설정 상한 8000 mm 초과 |
| 3 | `NO_RETURN` | `0xFFFF` |
| 4 | `SENSOR_INVALID` | 센서 invalid flag, `0xFFFF` |
| 5 | `NO_DATA` | 해당 구역 측정점 없음, `0xFFFF` |

각 구역 레코드의 `age_ms`는 해당 상태/거리 샘플이 측정된 뒤 패킷을 만들 때까지의 추정 경과시간입니다. 해당 구역에 여러 점이 있으면 레코드에 남긴 거리 샘플의 나이를 보냅니다. UART read 시점 기준에 입력 버퍼 여유 100 ms를 보수적으로 더하며, LiDAR 내부 하드웨어 timestamp는 아닙니다. 측정값이 없는 구역은 `0xFFFF`입니다. STM32는 구역별 허용 나이를 정하고 그보다 오래된 측정값을 현재값처럼 사용하지 않아야 합니다.

사이클 상태는 구역별 상태와 별개입니다. `PARTIAL`이어도 수신된 구역별 유효 측정은 함께 보내며, 누락된 점/사이클을 이전 사이클 값으로 채우지 않습니다. STM32는 `observed zone mask`로 어느 방향의 각도 샘플을 받았는지 확인할 수 있습니다. 해당 bit가 0이면 그 구역은 이번 사이클에서 관측되지 않았습니다. bit가 1이고 zone status가 `NO_RETURN`이면 그 구역은 관측했지만 유효한 거리 반환값이 없었습니다. 각 프레임의 coverage는 끝각−시작각에 다음 프레임까지의 한 칸을 더한 값(×8/7)입니다. 사이클 완성 여부는 각도 coverage 350° 이상, 유효 프레임 수가 기대치의 90% 이상, 8개 zone bit 모두 관측, 오류 프레임 0개일 때 complete로 판정합니다. 기대 프레임 기본값 52는 X1K SDK의 약 415 points/rev ÷ 8 points/frame을 바탕으로 하며 `--expected-frames`로 조정할 수 있습니다.

속도 상한 필드는 **차량 최대 안전속도 인증값이 아닙니다.** 사용자가 허용 이동거리 `D`를 실차 위험 분석으로 정해 `--max-unobserved-travel-mm D`를 설정하면 `D / max(sensor scan period, measured cycle elapsed)`를 mm/s로 담습니다. 기본은 미설정 `0xFFFF`입니다. 실제 수집 사이클이 재연결/처리 지연으로 늘어지면 이 값도 낮아집니다. `measured cycle elapsed`는 사이클 수집 시작부터 패킷 생성까지의 시간입니다. 전송 장애 동안 STM32가 패킷을 못 받은 시간은 STM32 watchdog이 감지해야 합니다. STM32 링크 복구 후에는 전송 대기 중 쌓인 LiDAR 입력 버퍼를 비우고 오래된 패킷을 재전송하지 않습니다. 순번 건너뜀과 수신 공백으로 손실을 알 수 있습니다. 이 속도 상한은 관측된 스캔 지연만 반영하며 이후 통신 지연·STM32 처리·제동거리는 포함하지 않습니다.

## Raspberry Pi 실행

Pi에서 전용 가상환경을 만들고 pyserial을 설치한 뒤 포트 이름을 확인합니다. 예시는 LiDAR가 USB UART, STM32가 USB 가상 COM으로 연결된 경우입니다.

```bash
cd /home/song/proj
python3 -m venv .venv
.venv/bin/pip install pyserial
.venv/bin/python lidar/lidar_bridge.py \
  --lidar-port /dev/ttyUSB0 \
  --stm32-port /dev/ttyACM0 \
  --forward-angle 0
```

시리얼 장치 권한 오류가 나면 Pi 사용자에게 `/dev/ttyUSB*` 및 `/dev/ttyACM*` 장치 접근 권한이 있는지 확인합니다(일반적으로 `dialout` 그룹).

포트는 실제 장치에 맞게 바꾸고, `--forward-angle`은 차체에 설치한 뒤 기준 방향을 측정해 넣습니다. 기본 baud는 두 포트 모두 115200 8-N-1입니다. 필요하면 `--lidar-baud`, `--stm32-baud`로 조정합니다. 사용자가 정한 이동 허용거리로 latency-only 속도 상한 필드를 포함할 때만 `--max-unobserved-travel-mm`을 추가합니다.

## STM32 수신 측 필수 처리

1. `C3 3C`를 찾고 version `3`의 고정 69바이트를 모읍니다.
2. 버전과 CRC를 확인하고, 실패 프레임은 데이터로 사용하지 않습니다.
3. 시퀀스로 중복/누락을 찾습니다. `PARTIAL` 및 `STARTUP_PARTIAL`은 완전 스캔과 구분합니다.
4. 구역별 status와 `age_ms`를 먼저 확인하고 신선한 `VALID` 거리만 정상 거리로 취급합니다. `TOO_CLOSE`는 `VALID` 거리와 구별합니다. `NO_RETURN`, `SENSOR_INVALID`, `NO_DATA`는 0 mm나 먼 거리로 해석하지 않습니다.
5. 패킷이 정해진 갱신 기한 안에 도착하지 않으면 데이터가 stale/유실된 것으로 처리합니다. 5.2 Hz 캡처 기준 정상 회전도 약 192 ms이므로, 실제 측정한 worst-case 주기와 여유를 반영해 타임아웃을 설정합니다.

Pi와 STM32를 UART로 연결하기 전에 양쪽의 IO 전압, GND, TX/RX를 확인합니다. Pi GPIO UART는 3.3 V 논리입니다. RS-232 신호나 5 V UART를 GPIO에 직접 연결하지 않습니다.

CRC는 우발적인 전송 오류를 검출할 뿐 송신자를 인증하거나 변조를 막지 않습니다. 이 UART는 보드 간 물리 연결로 보호하고, Raspberry Pi 원격 로그인은 SSH 키/강한 계정 인증과 방화벽으로 제한합니다. 이 프로그램은 입력 프레임만 받아들이며 네트워크 포트를 열지 않습니다. LiDAR 또는 STM32 UART가 분리되면 프로세스가 종료되거나 partial 상태를 보내게 되므로, 부팅 자동 실행을 구성할 때는 서비스 재시작 정책과 STM32의 독립 수신 watchdog을 함께 둡니다.

## 아직 실차에서 확정할 것

- 센서 정면각과 차체/범퍼 기준점
- 120 mm 하한, 8000 mm 상한이 실제 주행 상황에 맞는지
- 품질 바이트의 의미와 유효 임계값(현재는 원본값만 전달)
- 회전 속도 변동과 누락률의 worst-case
- STM32 UART 포트/baud 및 수신 watchdog 주기
- 주행속도 한계 산정에 필요한 처리 지연, 통신 지연, 제동거리와 허용 이동량
- STM32 펌웨어가 패킷 버전 3, 69바이트 길이, 구역별 측정 나이 및 zone coverage mask를 처리하도록 맞추기

## systemd 서비스 설치 템플릿

`deploy/lidar-bridge.service.example`은 부팅 시 자동 실행하는 systemd 템플릿입니다. 실제 Pi의 `/dev/serial/by-id/` 장치 이름과 정면각으로 `ExecStart`를 수정한 뒤 `/etc/systemd/system/lidar-bridge.service`에 설치합니다. `Restart=on-failure`와 120초당 최대 3회 시작 제한으로, 브리지 내부 재시도가 소진되면 서비스 매니저가 재기동합니다. 시작 제한까지 도달해 failed 상태가 되면 원인을 확인하고 `sudo systemctl reset-failed lidar-bridge && sudo systemctl start lidar-bridge`로 수동 재개합니다. 설치 후 `sudo systemctl daemon-reload`, `sudo systemctl enable --now lidar-bridge`를 실행합니다. 로그는 `journalctl -u lidar-bridge`에서 확인합니다.

## `run.py` (현재 사용하는 데이터 프로세스)

STM32 포트를 열지 않고 같은 69바이트 패킷과 값을 `/dev/shm/firecar/lidar.json`에 최신 1개만 둡니다. `lidar_bridge.py`와 다른 점:

- 프레임 사이 각도 빈틈(한 칸의 3배 초과)이 있거나 수집이 회전 주기의 1.5배를 넘으면 `PARTIAL`입니다. 시작각이 줄어들면 항상 새 회전으로 봅니다.
- 입력이 1024바이트 넘게 밀리면 버립니다. 센서가 없으면 `NO_DATA`를 내며 1초 간격으로 계속 재시도합니다.
- 패킷 속 나이는 `packet_ns` 시점 값입니다. 나중에 전송 프로그램은 그 뒤 지난 시간을 더하고 같은 sequence를 다시 보내지 않아야 합니다.

## 주행 요약 패킷 v1 (`run.py`, 초안, STM32 담당자와 확정 필요)

69바이트 v3와 함께 회전마다 1개 만든다. 21바이트, little-endian. Sequence는 같은 회전의 v3 패킷과 같다.
좌표: 앞 +x, 오른쪽 +y. 장애물은 `VALID` 점만 센다.

| 오프셋 | 크기 | 필드 | 정의 |
|---:|---:|---|---|
| 0 | 2 | Header | `C3 5C` |
| 2 | 1 | Version | `1` |
| 3 | 1 | Cycle status | v3와 같음 (0 complete, 1 partial, 2 startup) |
| 4 | 2 | Sequence | v3와 같음 |
| 6 | 2 | Front clear | 차 폭+양옆 여유 통로 안 가장 가까운 장애물까지 앞쪽 거리 mm |
| 8 | 2 | Left clear | 앞쪽 `side_lookahead_mm` 안에서 왼쪽 장애물까지 옆 거리 mm |
| 10 | 2 | Right clear | 같은 방식, 오른쪽 |
| 12 | 2 | Nearest | 모든 방향에서 가장 가까운 장애물 거리 mm |
| 14 | 2 | Nearest bearing | int16, 0.1도. 0 앞, + 오른쪽. 없으면 `0x7FFF` |
| 16 | 1 | Flags | bit0: 통로 안에 최소 거리보다 가까운 것 있음, bit1: 앞쪽에 반사 없는 점 있음(검은 물체일 수 있음) |
| 17 | 2 | Age | 이 회전에서 가장 오래된 점 측정 후 ms (v3처럼 100 ms 여유 포함). 점이 없으면 `0xFFFF` |
| 19 | 2 | CRC | CRC-16/CCITT-FALSE, 바이트 0~18 |

거리 값 `0xFFFE` = 봤지만 최대 거리 안에 장애물 없음, `0xFFFF` = 이번 회전에 그 방향을 못 봄.
"봤다"는 해당 각도 범위(앞 -60~60°, 왼쪽 -90~0°, 오른쪽 0~90°)의 10° 칸마다 점이 하나 이상 있다는 뜻이다. 한 칸이라도 비면 장애물이 보였더라도 `0xFFFF`다(빈 칸에 더 가까운 장애물이 있을 수 있음). Nearest는 받은 점 전체 기준이므로 Cycle status가 complete일 때만 "주변 전체에서 가장 가까움"이다.
bit1은 `NO_RETURN`만 센다. `SENSOR_INVALID` 점(캡처에서 회전마다 약 110~120개)은 세지 않는다.
차 폭 등은 `lidar/config.toml`에서 실측값으로 바꿔야 한다.
