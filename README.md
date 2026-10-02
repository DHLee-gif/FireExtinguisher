# FireCar 관제 웹페이지

자율주행 소방 RC카를 관제하기 위한 로컬 웹페이지입니다.
Flask와 MariaDB로 만들었고, RC카는 1대만 사용하는 것을 기준으로 했습니다.

## 파일 구성

웹 서버의 중심은 app.py입니다. 로그인, 메인 화면, 각종 로그 페이지가 여기에 있습니다.
RC카가 서버로 데이터를 보낼 때 쓰는 API는 api.py에 따로 분리했습니다.

DB 접속 정보나 카메라 스트림 주소 같은 설정값은 config.py에 모아두었습니다.
테이블 구조는 schema.sql에 있고, models.py는 이 테이블들을 파이썬에서 다루기 위한 파일입니다.
seed.py는 처음에 관리자 계정과 RC카 정보를 넣을 때 사용합니다.

state.py는 RC카에게 보낼 명령과 현재 동작, 물 잔량을 메모리에 저장합니다.
그래서 서버를 껐다 켜면 이 값들은 초기화됩니다.

simulator.py는 실제 RC카가 아직 없어서 테스트용으로 만든 가짜 RC카입니다.

## 설치

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 설정

config.py에서 DB 주소와 계정, 카메라 스트림 주소를 확인하고 필요하면 수정합니다.
현재 DB는 172.30.1.65:3306에 ktech 계정으로 접속하도록 되어 있고, DB 이름은 firecar입니다.
카메라 주소는 라즈베리파이 주소가 정해지지 않아서 임시로 넣어둔 상태입니다.

## DB 생성

아래 명령을 한 번 실행하면 firecar DB와 테이블이 만들어지고, 관리자 계정과 RC카(FireCar-01)가 등록됩니다.
실행하면 관리자 비밀번호를 물어보는데, 비밀번호는 해시해서 저장됩니다.

```powershell
python seed.py --schema --login-id admin --name 관리자
```

mysql 클라이언트가 있다면 schema.sql을 직접 실행한 다음 seed.py만 돌려도 됩니다.

```powershell
mysql -h 172.30.1.65 -u ktech -p < schema.sql
python seed.py --login-id admin --name 관리자
```

이미 등록된 계정이나 RC카는 건너뛰기 때문에 여러 번 실행해도 문제없습니다.

## 서버 실행

```powershell
python app.py
```

외부 기기에서도 접속할 수 있도록 0.0.0.0:5000으로 실행됩니다.
같은 와이파이에 연결된 휴대폰이나 다른 PC에서 http://PC의IP:5000 으로 들어가면 됩니다.
접속이 안 되면 Windows 방화벽에서 5000번 포트를 허용해야 합니다.

지금은 DB 연결 전이라 테스트를 위해 아무 아이디로나 로그인되게 해두었습니다.
실제 계정으로 로그인하려면 config.py의 LOGIN_BYPASS를 False로 바꾸면 됩니다.

## 시뮬레이터 실행

서버를 켜둔 상태에서 터미널을 하나 더 열고 실행합니다.

```powershell
python simulator.py
```

실행하면 웹에서 출격 버튼을 누를 때까지 기다립니다.
출격하면 순찰을 시작하고, 화재 감지, 분사, 재분사, 진화 완료 순서로 진행됩니다.
그다음 모터 에러가 발생하는데, 웹에서 재개 버튼을 누르면 다시 진행됩니다.
마지막으로 물이 부족해져서 기지로 돌아가 급수하고, 순찰 후 기지로 복귀하면 끝납니다.

버튼 없이 자동으로 끝까지 돌려보고 싶으면 --auto 옵션을 붙이면 됩니다.
진행 중에 긴급 정지나 복귀 버튼을 누르면 시뮬레이터도 그에 맞게 반응합니다.

## 웹 페이지

로그인하면 메인 화면에 인사말과 출격 버튼이 나옵니다.
출격을 누르면 라이브 화면으로 바뀌고, 카메라 영상과 RC카의 현재 동작, 상태, 물 잔량이 3초마다 갱신됩니다.
새로운 화재가 감지되면 팝업으로 알려주고, 긴급 정지, 복귀, 재개 버튼으로 RC카에 명령을 보낼 수 있습니다.

재개 버튼은 해결되지 않은 에러가 있을 때 누르면 그 에러를 해결 처리하고,
상태 로그에 MANUAL_RESOLVED와 PATROL_RESUME 기록을 남긴 뒤 RC카에 재개 명령을 보냅니다.

상단 메뉴에서는 관리자 정보, Fire Event, Status Log, Water Log 페이지로 이동할 수 있습니다.
관리자 정보에서는 RC카가 최근 10초 안에 통신했는지로 온라인 여부를 보여줍니다.
Fire Event 상세 페이지에서는 진화 전후 사진과 분사 기록을 함께 볼 수 있습니다.

## RC카 연동 API

RC카는 아래 API로 서버와 통신합니다. 로그인 없이 JSON으로 주고받습니다.

```
POST /api/heartbeat           현재 동작과 물 잔량 전송, 마지막 통신 시각 갱신
GET  /api/command             대기 중인 명령 받아가기 (start, stop, return, resume)
POST /api/fire                진화 전 사진과 온도, 인식 신뢰도로 화재 등록
POST /api/fire/<id>/spray     분사 기록 추가
POST /api/fire/<id>/image     진화 후 사진 업로드
PUT  /api/fire/<id>           최종 상태와 종료 시각 기록
POST /api/status              상태 로그 기록
POST /api/water               수위 로그 기록
```

heartbeat 예시입니다.

```json
{"action": "patrol", "water_level": 72.5}
```

action에는 idle, patrol, extinguish, homing, refill, stopped 중 하나를 보내면 됩니다.
인식 신뢰도는 0에서 1 사이 값으로 보내면 화면에는 퍼센트로 표시됩니다.
사진은 static/uploads 폴더에 저장되고, DB에는 파일 경로만 저장됩니다.

명령은 RC카가 /api/command를 호출할 때마다 하나씩 가져갑니다.
긴급 정지는 다른 명령보다 먼저 전달되도록 했습니다.
