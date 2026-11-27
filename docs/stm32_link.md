# Pi → STM32 연결 (`stm32/run.py`)

Pi가 만든 선·LiDAR·불 패킷을 USB로 STM32(Nucleo-F446RE, firecar 펌웨어)에 보낸다.
**주행 판단은 STM32가 한다. Pi는 패킷을 전달만 한다.**

## 연결

- Pi USB-A 단자 ↔ Nucleo USB (ST-LINK). Pi에서는 `/dev/ttyACM0` (`config.toml`의 `port = "auto"`가 자동으로 찾음).
- 115200 8-N-1. STM32 쪽은 USART2 (PC 터미널과 같은 포트).
- 텍스트 명령(`F 20`, `?`, `P` …)과 패킷이 같은 선으로 간다. 텍스트는 ASCII라서 `0xC3`으로 시작하지 않으므로
  STM32가 첫 바이트로 구분한다.

## 보내는 패킷

| 공유 값 | 필드 | 패킷 | 크기 | 주기 |
|---|---|---|---:|---:|
| `line` | `packet` | 선 v2 `C3 4C` ([line_packet.md](line_packet.md)) | 25 | 15Hz |
| `lidar` | `summary_packet` | 주행 요약 v1 `C3 5C` ([lidar_packet.md](lidar_packet.md)) | 21 | 5.2Hz |
| `lidar` | `packet` | 8구역 v3 `C3 3C` | 69 | 5.2Hz |
| `fire` | `packet` | 불 v1 `C3 6C` ([fire.md](fire.md)) | 22 | 2Hz |

`stm32/config.toml`의 `[sources]`에서 고른다.

## 전송 규칙 (`stm32/link.py`)

- **같은 Sequence는 다시 보내지 않는다.** 프로세스가 죽어도 마지막 파일이 남기 때문이다.
- **Pi 안에서 기다린 시간을 나이 필드에 더하고 CRC를 다시 계산한다.** 기다린 시간 = 지금 − 공유 파일이 쓰인 시각.
  더하는 필드: 선 `Age`, 요약 `Age`, 불 `Seen`·`Age`, v3 구역별 `age_ms`. `0xFFFF`(값 없음)는 그대로 둔다.
- **`max_delay_ms`(기본 300)보다 오래 기다린 패킷은 버린다.**
- CRC가 틀리거나 모르는 패킷은 보내지 않고 센다.
- 보드가 빠져 있어도 종료하지 않고 1초마다 다시 찾는다. 다시 연결되면 그동안 쌓인 값은 버리고 새 값부터 보낸다.
- STM32가 보내는 글자는 `[stm32] …`로 로그에 나온다. 10초마다 보낸 개수를 출력한다.

## STM32 쪽 (firecar `main.c`)

- `0xC3` → 두 번째 바이트로 길이 결정 → 길이만큼 모음 → CRC·버전 확인 → 구조체 저장.
- `P` 명령: 받은 최신 값 출력. `?` 명령: `pi OK/LOST`, 종류별 받은 개수, CRC·형식 오류 수.
- 0.5초 동안 정상 패킷이 없으면 `LOST` (watchdog). 자율 주행은 이 상태에서 멈춰야 한다.

## 시험

PC에서 (Pi 없이): `python stm32/tools/fake_pi.py COMx` — 가짜 패킷을 보내고 `P` 결과를 보여 준다.

Pi에서 (터미널 두 개):

```bash
# 1) 센서 프로세스들 (STM32 전송만 빼고)
.venv/bin/python main.py --no-stream --no-stm32
# 2) 전송 + 1초마다 STM32가 받은 값 출력
PYTHONPATH=. .venv/bin/python stm32/run.py --show 1
```
