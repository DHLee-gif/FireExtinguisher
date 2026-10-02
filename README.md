# FireCar 관제 (자율주행 소방 RC카 관제용 로컬 웹페이지)

Flask + MariaDB(SQLAlchemy/PyMySQL) 기반. RC카 1대를 관제한다.

## 파일 구성

| 파일 | 설명 |
|---|---|
| `config.py` | DB 접속 정보, `STREAM_URL`(카메라 MJPEG 주소), 포트 등 설정 |
| `schema.sql` | `firecar` DB 및 테이블 생성 SQL |
| `seed.py` | 초기 관리자 계정 + device 1행(FireCar-01) 입력 |
| `app.py` | 웹 페이지 + 관제 화면용 API (`/api/live`, `/api/sortie`, `/api/control/<cmd>`) |
| `api.py` | RC카 연동 API (로그인 불필요) |
| `state.py` | 명령 큐 / 현재 동작·수위 (메모리, 서버 재시작 시 초기화) |
| `simulator.py` | RC카 시뮬레이터 |

## 1. 설치

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 2. 설정

`config.py` 에서 확인/수정한다. 환경변수로도 덮어쓸 수 있다.

| 항목 | 기본값 | 환경변수 |
|---|---|---|
| DB 호스트/포트 | `172.30.1.65:3306` | `FIRECAR_DB_HOST`, `FIRECAR_DB_PORT` |
| DB 계정 | `ktech` / `ktech1234` | `FIRECAR_DB_USER`, `FIRECAR_DB_PASSWORD` |
| DB 이름 | `firecar` | `FIRECAR_DB_NAME` (schema.sql 은 `firecar` 고정) |
| 카메라 스트림 | `http://raspberrypi.local:8000/stream.mjpg` | `FIRECAR_STREAM_URL` |
| 서버 포트 | `5000` | `FIRECAR_PORT` |

## 3. DB 생성 + seed

**방법 A - seed.py 로 한 번에** (DB 생성 권한이 있는 계정이어야 함)

```powershell
python seed.py --schema --login-id admin --name 관리자
# 비밀번호 입력 프롬프트가 뜸 (--password 로 직접 지정 가능)
```

**방법 B - mysql 클라이언트로 schema 실행 후 seed**

```powershell
mysql -h 172.30.1.65 -u ktech -p < schema.sql
python seed.py --login-id admin --name 관리자
```

- 비밀번호는 werkzeug `generate_password_hash` 로 해시되어 저장된다.
- 이미 존재하는 관리자/device 는 건너뛰므로 여러 번 실행해도 안전하다.

## 로그인 (개발 모드)

현재 `config.py` 의 `LOGIN_BYPASS = True` 로 되어 있어 **아무 아이디/비밀번호로 로그인**된다.
(입력한 아이디가 화면의 이름으로 표시됨) 실제 계정 확인을 하려면 `FIRECAR_LOGIN_BYPASS=0` 으로 실행한다.

```powershell
$env:FIRECAR_LOGIN_BYPASS="0"; python app.py
```

## 4. 서버 실행

```powershell
python app.py
```

- `0.0.0.0:5000` 으로 실행되므로 같은 네트워크의 다른 기기에서 `http://<PC IP>:5000` 으로 접속할 수 있다.
  (Windows 방화벽에서 5000 포트 인바운드 허용이 필요할 수 있음)
- 디버그 모드: `$env:FIRECAR_DEBUG="1"; python app.py`
  (외부에 디버거가 노출되므로 신뢰할 수 있는 네트워크에서만 사용)

## 5. 시뮬레이터 실행

서버를 켠 상태에서 다른 터미널에서 실행한다.

```powershell
python simulator.py              # 웹에서 [출격] → (에러 발생 시) [재개] 버튼을 눌러 진행
python simulator.py --auto       # 버튼 없이 자동 진행 (MOTOR_STALL 에러는 미해결로 남음)
python simulator.py --server http://192.168.0.10:5000 --step 3
```

시나리오: heartbeat(2초 주기) → 출격 대기 → 순찰 → 화재 감지(진화 전 사진) → 분사 → 재분사
→ 진화 후 사진 + 진화 완료 → 모터 에러 → 재개 대기 → 물 부족 → 귀소 → 급수 → 순찰 → 기지 복귀

시뮬레이터 실행 중 웹의 **긴급 정지**(→ 재개 시 계속), **복귀**(→ 귀소 후 종료) 버튼도 반영된다.
사진은 시뮬레이터가 생성한 더미 PNG 를 사용한다.

## 웹 페이지

| 경로 | 내용 |
|---|---|
| `/login` | 로그인 (미로그인 시 모든 페이지가 여기로 이동) |
| `/` | 인사 + 출격 버튼 → 라이브 화면 (스트림, 동작/상태/물 잔량 3초 폴링, 화재 알림 팝업, 긴급 정지/복귀/재개) |
| `/admin` | 관리자 이름·아이디, RC카 이름·연결 상태(last_seen 10초 이내 = 온라인)·마지막 통신 |
| `/fire`, `/fire/<id>` | 화재 이벤트 목록 / 진화 전후 사진 + 분사 기록 |
| `/status` | 상태 로그 (레벨 필터, 미해결 에러만 보기) |
| `/water` | 현재 물 잔량 + 수위 로그 |

**재개 버튼**: 미해결 error 행이 있으면 `resolved_at` 을 기록하고 status_log 에
`MANUAL_RESOLVED`, `PATROL_RESUME` 행을 추가한 뒤 RC카에 `resume` 명령을 보낸다.

## RC카 연동 API (JSON, 로그인 불필요)

| 메서드 | 경로 | 본문 | 응답 |
|---|---|---|---|
| POST | `/api/heartbeat` | `{"action": "patrol", "water_level": 72.5}` | `{"ok": true}` |
| GET | `/api/command` | - | `{"command": "start" \| "stop" \| "return" \| "resume" \| null}` |
| POST | `/api/fire` | multipart: `image`(파일), `temperature`, `vision_score` | `{"event_id": 1}` |
| POST | `/api/fire/<id>/spray` | `{"duration_ms": 3000, "temp_after": 95.2}` | `{"spray_id": 1}` |
| POST | `/api/fire/<id>/image` | multipart: `image`(진화 후 사진) | `{"image_id": 2}` |
| PUT | `/api/fire/<id>` | `{"status": "extinguished"}` (`closed_at` 생략 시 종료 상태면 현재 시각) | `{"ok": true}` |
| POST | `/api/status` | `{"level": "error", "code": "MOTOR_STALL", "message": "..."}` | `{"log_id": 1}` |
| POST | `/api/water` | `{"water_level": 15, "action": "low"}` | `{"log_id": 1}` |

- `action`(heartbeat): `idle`, `patrol`(순찰 중), `extinguish`(진화 중), `homing`(귀소 중), `refill`(급수 중), `stopped`(정지)
- `vision_score`: 0~1 (화면에는 % 로 표시)
- 사진은 `static/uploads/` 에 저장되고 DB 에는 `uploads/파일명` 경로만 저장된다. (jpg, jpeg, png)
- 명령 큐는 메모리 변수이며 `/api/command` 호출 1회에 명령 1개씩 꺼내간다. 긴급 정지는 대기 중인 명령을 비우고 맨 앞에 들어간다.
- 출격 상태는 RC카가 `idle` 이 아닌 동작을 보내면 시작, 다시 `idle` 을 보내면(기지 도착) 종료되어 메인 화면으로 돌아간다.
