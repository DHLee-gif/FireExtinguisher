# Wi-Fi 영상 전송 규격 (차 → 웹앱)

웹앱 담당자에게 주는 문서. 웹앱 서버는 아래처럼 차의 연결을 받기만 하면 된다.

## 요약

- **차(Raspberry Pi)가 웹앱 서버로 연결한다.** 서버가 차에 연결하는 게 아니다. 그래서 차가 공유기 뒤에 있어도 된다.
- 연결: WebSocket. 주소는 차의 `stream/config.toml`의 `server_url` (예: `wss://example.com/ingest`).
- 영상: **JPEG 사진 1장 = binary 메시지 1개.** 초당 10장 (설정 `fps`). 이어서 보여 주면 영상이 된다.
- 크기: 가로 최대 640픽셀 (설정 `width`), 장당 약 20KB → 약 200KB/s.
- 화질·크기·초당 장수는 차의 `stream/config.toml`에서 바꾼다.

## 메시지

차가 보내는 것만 있다. 서버가 차로 보낼 것은 없다 (보내도 무시한다).

| 종류 | 내용 | 언제 |
|---|---|---|
| text | `{"type":"hello","car_id":"firecar-1","format":"jpeg","max_width":640,"fps":10}` | 연결 직후 1번 |
| text | `{"type":"status","camera":"ok"}` | 카메라 영상이 (다시) 들어오기 시작할 때 |
| text | `{"type":"status","camera":"no_frame"}` | 카메라 영상이 끊겼을 때, 끊긴 동안 2초마다 |
| binary | JPEG 바이트 (`FF D8`로 시작) | 새 영상마다 |

- 같은 사진을 두 번 보내지 않는다.
- 네트워크가 느리면 밀린 사진을 쌓지 않고 **건너뛰어 최신 사진만** 보낸다. 화면이 잠깐 끊겨도 늦게 따라오지는 않는다.
- 연결이 끊기면 차가 1초에서 시작해 최대 10초 간격으로 계속 다시 연결한다. 새 연결은 다시 `hello`부터 시작한다.
- 웹앱이 인증을 요구하면 차의 `token`에 넣는다. 연결할 때 `Authorization: Bearer <token>` 헤더로 보낸다.
- 압축(permessage-deflate)은 쓰지 않는다 (JPEG는 이미 압축됨).

## 웹앱이 할 일 (예)

1. `/ingest` 같은 WebSocket 주소에서 차의 연결을 받는다.
2. binary 메시지(JPEG)를 받을 때마다 최신 1장만 기억한다.
3. 브라우저에 최신 사진을 넘긴다. 예: 브라우저용 WebSocket으로 그대로 전달하고, 브라우저는
   `img.src = URL.createObjectURL(blob)`로 바꿔 끼운다. 느린 브라우저에게는 밀린 사진을 버리고 최신만 준다.
4. `status`의 `camera`와 차 연결 여부를 화면에 보여 주면 "화면이 멈춘 이유"(차가 끊김 / 카메라 문제)를 알 수 있다.

`stream/dev_server.py`가 이 방식대로 만든 **동작하는 예시**다 (Python websockets, 100줄 남짓). 그대로 참고하면 된다.

## 시험 방법

```bash
# 1) 가상 웹앱 켜기
.venv/bin/python stream/dev_server.py
# 2) 차 쪽 전체 실행 (또는 stream만: PYTHONPATH=. .venv/bin/python stream/run.py — camera/capture.py가 돌고 있어야 함)
.venv/bin/python main.py
# 3) 브라우저로 http://<서버 주소>:8090/
```

장치 없는 자동 테스트: `stream/tests/` (차 → 가상 웹앱 → 시청자까지 한 번에 확인하는 테스트 포함).

## 차 쪽 구현 (`stream/run.py`)

- 카메라를 직접 열지 않는다. `camera/`가 공유하는 최신 영상(`common/framebus.py`)만 읽는다.
- 낮은 우선순위(`nice 10`)로 돈다. 선 인식·LiDAR가 먼저다.
- 0.5초(`max_frame_age_s`)보다 오래된 영상은 보내지 않고 `no_frame`을 보낸다.
- 한 장을 보내는 데 5초(`send_timeout_s`) 넘게 걸리면 연결이 죽은 것으로 보고 다시 연결한다.
