# 소방 RC카 — Raspberry Pi 쪽 (학원 프로젝트)

Raspberry Pi 4가 LiDAR 거리, 선 위치, 불 위치를 만들어 STM32에 넘기고, 카메라 화면을 Wi-Fi로 웹앱에 보낸다.
**주행 판단과 모터·소화 장치 제어는 STM32가 한다. Pi는 모터 명령을 만들지 않는다.**

## 문서 목록

| 문서 | 내용 |
|---|---|
| [status.md](status.md) | **여기부터 읽기.** 단계별 진행 상황, 확인된 것·안 된 것, 결정 사항, 다음 할 일 |
| [setup.md](setup.md) | 설치, 하드웨어 연결(LiDAR UART, 부팅 설정 변경 내역), 실행, 전원 켜면 자동 실행 |
| [timing.md](timing.md) | 처리 주기(LiDAR 한 바퀴 기준)와 CPU 코어 배분, 차 속도 상한 |
| [testing.md](testing.md) | 테스트, 규칙 검사, 점검 절차(카메라·Pi 상태·LiDAR·선 검증, 고장 격리 시험) |
| [stream.md](stream.md) | Wi-Fi 영상 전송 규격 (웹앱 담당자에게 줄 문서) |
| [fire.md](fire.md) | 불 감지: 사진 수집 → 라벨링 → PC 학습 → Pi에 넣기, 불 패킷 v1 규격 |
| [lidar_packet.md](lidar_packet.md) | LiDAR 처리와 STM32 패킷 v3(69바이트)·주행 요약(21바이트) 규격 |
| [line_packet.md](line_packet.md) | 선 패킷 v2(25바이트) 규격 |

## 구조

각 기능은 **별도 프로세스**로 돈다. `main.py`가 모두 띄우고, 죽으면 다시 띄운다.

```text
전원 ON → systemd(deploy/firecar.service) → main.py
  ├ camera/  카메라 촬영 → 공유 영상 (/dev/shm/firecar/frame.bin, 최신 1장, 약 30fps)
  ├ line/    공유 영상 → 선 인식 → line.json (선 패킷 v2 포함, 15Hz)
  ├ lidar/   LiDAR UART → 해석 → lidar.json (패킷 v3 + 주행 요약 포함)
  ├ fire/    공유 영상 → YOLO(ONNX) → fire.json (불 패킷 v1 포함, 2Hz)
  ├ stream/  공유 영상 → JPEG → WebSocket → 웹앱 서버 (10fps)
  └ stm32/   (아직 없음) line.json·lidar.json의 패킷을 STM32 UART로 전송
```

프로세스끼리는 `/dev/shm/firecar/`(RAM) 파일로만 주고받는다. 쓰는 쪽은 파일을 통째로 바꿔치기(atomic replace)하고
읽는 쪽은 잠그지 않는다. 그래서 하나가 느리거나 죽어도 다른 쪽이 막히지 않는다.

| 폴더 | 역할 | 상태 |
|---|---|---|
| `camera/` | 카메라를 여는 **유일한** 곳. 최신 영상 1장 공유 | 동작 |
| `line/` | 선 1개 인식 → 치우침·각도·신뢰도 → 선 패킷 | 가상 영상으로 동작, 실제 선 미확인 |
| `lidar/` | `run.py`: LiDAR 수신·해석 → 패킷 | 실제 센서로 동작 |
| `stream/` | 카메라 화면 → 웹앱 (Wi-Fi) | 가상 웹앱으로 동작 |
| `fire/` | 불 감지 (YOLO, Pi는 추론만) | 동작 (공개 학습 모델, 시험 사진 감지 88%·오탐 0%) |
| `stm32/` | STM32로 패킷 전송 | 시작 안 함 (나중에) |
| `common/` | 영역끼리 공유하는 규격만 (`framebus.py` 영상, `valuebus.py` 값) | 동작 |
| `tools/check.py` | 규칙 검사 + 전체 테스트 | |
| `deploy/` | systemd 서비스 파일 | |
| `main.toml` | 프로세스별 CPU 코어 ([timing.md](timing.md)) | |

## 원칙 (코드를 고칠 때 지킬 것)

- **한 프로세스가 죽거나 느려져도 나머지는 계속 돈다.** 밀린 데이터는 버리고 최신만 쓴다.
- **영역끼리 import하지 않는다.** 공유할 것은 `common/`에만 두고, `common/`은 영역 코드를 import하지 않는다.
- **카메라는 `camera/`만 연다.** 다른 영역은 공유 영상만 읽는다. **시리얼 포트는 `lidar/`·`stm32/`만** 연다.
- **오래된 값은 "값 없음"으로 보낸다.** 모든 패킷에 상태·나이(ms)가 있다. "불 없음"과 "불 값 없음"은 다르다.
- **프로세스끼리 영향을 주지 않는다.** 각자 정한 주기로만 돌고 CPU 코어를 나눠 쓴다 ([timing.md](timing.md)).
- **우선순위: 선 인식·LiDAR > 불 감지 > 스트리밍.** 불 감지는 `nice 5`, 스트리밍은 `nice 10`으로 돌고,
  둘 다 계속 죽어도 다른 프로세스를 멈추지 않는다.
- **조정할 값(선 색, 임계값, 노출, 포트, 서버 주소)은 코드가 아니라 각 영역의 `config.toml`에 둔다.** 선 색 기본값은 흰색.
- **불은 실제 불꽃(휴지·촛불·라이터).** 여러 번 연속 감지됐을 때만 인정한다.
- **LiDAR 패킷 v3(69바이트)를 바꾸면 STM32 펌웨어도 함께 바꿔야 한다.** 펌웨어는 이 저장소에 없다.
- **예외를 조용히 삼키지 않는다** (`except:` 금지, `except Exception: pass` 금지).
- 테스트는 실제 장치 없이 돌아야 한다. 파일 이름은 `<영역>/tests/test_*.py`.

위 규칙 중 import·카메라·시리얼·예외 규칙은 `tools/check.py`가 자동으로 검사한다.

## 주의

- `/boot/firmware/config.txt`, `cmdline.txt`는 OS 파일이다. 고치기 전에 백업하고, 재부팅 전에 팀에 알린다.
- sudo는 암호가 필요하다.
- 홈 폴더의 `~/mjpg-streamer`는 이 프로젝트에서 쓰지 않는다. 카메라를 직접 열어서 `camera/`와 충돌하니 실행하지 않는다.
