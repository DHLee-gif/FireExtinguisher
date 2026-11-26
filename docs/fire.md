# 불 감지 (`fire/`)

실제 불꽃(휴지·촛불·라이터)을 카메라로 찾는다. **PC에서 YOLO를 학습하고, Pi는 학습된 모델로 추론만 한다.**
Pi에는 PyTorch를 설치하지 않는다. 모델은 ONNX 파일로 바꿔서 OpenCV로 돌린다.

## 현재 상태 (2026-11-26)

**지금 Pi에서 불 감지가 동작한다.** 공개된 학습 모델을 받아 쓰고 있다 (직접 학습한 모델은 아직 없음).

| 항목 | 상태 |
|---|---|
| Pi 추론 프로세스 `fire/run.py` | 완료. `main.py`가 같이 띄운다 (2Hz, 코어 2) |
| 연속 감지 판정, 불 패킷 v1 (22바이트) | 완료 (테스트 16개) |
| **모델 `fire/models/fire.onnx`** | **설치됨.** 공개 모델 `rabahdev/fire-smoke-yolov8n` (아래 "지금 쓰는 모델") |
| 성능 (D-Fire 시험 사진 600장) | 불 사진 88% 감지, 불 없는 사진 오탐 0%, 1장 약 300ms |
| 실제 서비스 확인 | 불 감지 2.0Hz, 선 14.6Hz·LiDAR 5.3Hz 유지, 카메라 화면 → `NO_FIRE` |
| 실제 불꽃·화면 속 불꽃 시험 | **미확인** (실제 불을 쓸 수 없음. 휴대폰 화면 등으로 시험할 것) |
| 직접 학습 (Colab) | 준비만 됨: `~/fire-train/dfire_fire.zip`, `fire/train/colab_train.ipynb` |

## 지금 쓰는 모델

- 출처: Hugging Face `rabahdev/fire-smoke-yolov8n` (`best.pt`). D-Fire로 학습한 YOLOv8n, 클래스 0 = 연기, 1 = 불.
  라이선스 AGPL-3.0 (ultralytics에서 이어받음. 학원 프로젝트는 문제없음).
- **Pi에서 직접 학습하지 않은 이유:** 1 epoch에 약 2시간(40 epoch면 80시간 이상)이 걸렸고 선 인식을 느리게 만들었다.
- **안전하게 변환:** `.pt`는 열 때 안의 코드가 실행될 수 있는 형식이라, `fire/train/convert_pretrained.py`로
  ① 열지 않고 안에 든 클래스 목록을 검사하고(PyTorch·ultralytics 부품만 있었음) ② PyTorch 안전 모드
  (`weights_only=True` + 허용 목록)로 읽어 ③ 새로 만든 모델에 가중치만 옮겨 ONNX(입력 320)로 바꿨다.
  ```bash
  cd ~/fire-train   # 학습용 가상환경 (아래 1번)
  .venv/bin/python /home/song/proj/fire/train/convert_pretrained.py pretrained_rabahdev/best.pt pretrained_rabahdev --sizes 320
  cp pretrained_rabahdev/fire_320.onnx /home/song/proj/fire/models/fire.onnx
  ```
- 설정 (`fire/config.toml`): `fire_class = 1`, `score_threshold = 0.25`, `input_size = 320`.

시험 사진 600장 (불 400 / 불 없음 200, 이 모델 학습에 안 쓰인 D-Fire test에서 뽑음, `fire/train/evaluate.py`):

| 입력 | 기준 점수 | 불 사진 감지 | 오탐 | 1장 처리 (1스레드) |
|---:|---:|---:|---:|---:|
| 320 | 0.5 | 67% | 0% | 296ms |
| 320 | 0.35 | 83% | 0% | 295ms |
| **320** | **0.25 (사용)** | **88%** | **0%** | **약 300ms** |
| 320 | 0.15 | 92% | 1% | 293ms |
| 640 | 0.5 | 76% | 0% | 1,023ms (2Hz에 못 맞춤) |

- 640이 더 정확하지만 1장에 1초라서 2Hz 주기([timing.md](timing.md))를 못 지킨다. 그래서 320.
- 0.15부터 오탐이 생겨서 여유를 두고 0.25. 실제로는 5장 중 3장 연속 조건이 한 번 더 거른다.
- 사진에 상자를 그려 확인: 연기만 있는 사진, 주황색 노을 → 불 없음. 산불·야간 불꽃 → 불꽃에 상자.
- 실제 전등·햇빛·주황색 물체에서 오탐이 나면 `score_threshold`를 0.35~0.5로 올린다.

다른 공개 모델도 찾아봤다: ONNX로 공개된 `aryantyagiase/yolov8-fire-smoke-detection`은 올라간 파일이 잘려 있어(8MB) 쓸 수 없었다.

**더 좋게 하려면:** 아래 2번(Colab)으로 우리 데이터(불만, 320 입력)에 맞춰 직접 학습하거나, 실제 불꽃을 찍을 수 있으면
이 카메라 사진을 섞어 학습한다. 새 모델이 불 전용이면 `fire_class = 0`으로 바꾼다. 바꾸기 전에 `evaluate.py`로 지금 모델과 비교한다.

## 1. 데이터셋: D-Fire (공개, CC0)

실제로 불을 붙여 찍을 수 없어서 공개 데이터셋 **D-Fire**를 쓴다 (github.com/gaiasd/DFireDataset, CC0 1.0 = 자유 사용).
불·연기 사진 21,527장, YOLO 라벨 (D-Fire는 0 = 연기, 1 = 불. 사진에 상자를 그려 1이 불임을 확인했다).

`fire/train/download_dfire.py`가 Hugging Face 사본(badsaarow/d-fire)에서 받아 **불 클래스만 남긴 YOLO 데이터셋**을 만든다.
연기만 있는 사진과 아무것도 없는 사진은 "불 아님"으로 넣는다 (오탐 방지).

| 구분 | 사진 | 불 있음 | 불 없음 |
|---|---:|---:|---:|
| train | 3,825 | 2,544 | 1,281 |
| val | 675 | 456 | 219 |
| test (학습에 안 씀, 마지막 성능 확인용) | 600 | 400 | 200 |

```bash
# 학습용 가상환경 (프로젝트 .venv와 따로): ~/fire-train
python3 -m venv ~/fire-train/.venv
~/fire-train/.venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
~/fire-train/.venv/bin/pip install ultralytics onnx onnxslim pyarrow
~/fire-train/.venv/bin/python fire/train/download_dfire.py ~/fire-train/dfire    # 약 3GB 받음, 30분 정도
```

결과는 `~/fire-train/dfire/`(사진 약 220MB). Colab에 올릴 압축 파일은 `~/fire-train/dfire_fire.zip`.
(파일을 하나씩 받으면 Hugging Face가 요청 제한(429)을 걸어서 큰 parquet 묶음으로 받는다.)

나중에 실제 불꽃 사진을 찍을 수 있게 되면 `fire/collect.py`로 이 카메라 사진을 모아 라벨링해서 섞는다.
이 카메라로 찍은 사진이 들어가면 실제 성능이 좋아진다.

```bash
cd /home/song/proj/fire
PYTHONPATH=.:.. ../.venv/bin/python collect.py dataset/raw/candle_50cm --every 0.5 --count 100
```

## 2. 학습: Google Colab (무료 GPU)

**Pi에서는 학습하지 않는다.** 시험해 보니 Pi에서 1 epoch에 약 2시간(40 epoch면 80시간 이상)이 걸렸고,
차량 프로세스의 CPU를 빼앗았다 (선 인식이 29Hz → 18~21Hz로 떨어짐). [timing.md](timing.md) 참고.

1. `~/fire-train/dfire_fire.zip`(220MB)을 Google Drive "내 드라이브" 맨 위에 올린다.
2. https://colab.research.google.com 에서 **파일 → 노트북 업로드**로 `fire/train/colab_train.ipynb`를 연다.
3. **런타임 → 런타임 유형 변경 → T4 GPU**.
4. 셀을 위에서부터 차례로 실행한다. Drive 연결을 묻으면 허용한다.
5. 학습(약 15~30분)이 끝나면 마지막 셀이 `fire.onnx`를 내려받는다 (Drive에도 저장됨).
   5번 셀의 시험 결과(precision, recall, mAP50)도 적어 둔다.

설정: `yolov8n`(가장 작은 모델, Pi CPU용), `imgsz=320`(= `fire/config.toml` `input_size`), 60 epoch, 15 epoch 동안
나아지지 않으면 멈춤. ONNX는 `opset=12`로 export (Pi의 OpenCV 4.10 DNN이 읽을 수 있게).

GPU가 있는 PC에서 해도 된다: 위 학습용 가상환경을 만들고 `DEVICE=0 fire/train/train.sh 60`.
(`train.sh`는 Pi에서도 돌지만 위 이유로 권장하지 않는다.)

참고: ultralytics는 AGPL-3.0이다. 학원 프로젝트는 문제없지만 상업용이면 확인이 필요하다.

## 4. Pi에 넣기

```bash
scp best.onnx song@<Pi 주소>:/home/song/proj/fire/models/fire.onnx
sudo systemctl restart firecar        # 서비스로 돌 때. 직접 실행 중이면 main.py를 다시 시작
```

확인:
```bash
cd /home/song/proj/fire
PYTHONPATH=.:.. ../.venv/bin/python preview.py /tmp/fire.jpg           # 지금 카메라 화면에 상자 그리기
PYTHONPATH=.:.. ../.venv/bin/python preview.py /tmp/fire.jpg 사진.jpg   # 저장된 사진으로
cd .. && PYTHONPATH=. .venv/bin/python monitor.py                       # fire 값 (status, hits, target)
```

## 5. 실제 시험 (모델을 넣은 뒤)

0. 실제 불을 쓸 수 없으면: 휴대폰·모니터에 불꽃 사진·영상을 띄워 카메라에 비춘다 (화면 반사 때문에 실제보다 어려울 수 있다).
   test 사진으로는 `preview.py`에 사진 경로를 주어 확인한다.
1. 촛불·라이터·타는 휴지를 30cm, 1m, 2m, 3m에서 → `FIRE`가 되는지, `target.x`가 불의 좌우 위치와 맞는지
2. 불 없이 전등·햇빛·주황색 물체 → `FIRE`가 되면 안 된다 (`SUSPECT`가 가끔 나오는 건 괜찮다)
3. 오탐이 많으면 "불 아님" 사진을 더 모아 다시 학습하거나 `score_threshold`를 올린다.
   놓치는 게 많으면 그 조건의 불 사진을 더 모은다.
4. 속도: 로그의 `stopped: N frames, X fps`, `top`으로 CPU. **선 인식이 느려지면 안 된다** (선 30fps 유지).
   느리면 `max_fps`나 `threads`를 줄인다.

## 동작 방식 (`fire/run.py`)

- 공유 영상 → 320×320으로 맞춤(비율 유지, 회색 여백) → YOLO → 점수가 `score_threshold`를 넘는 것만, 겹친 상자 제거
- **연속 감지:** 최근 `window`(5)장 중 `confirm_hits`(3)장 이상에서 보이면 `FIRE`. 한 번 확정되면 최근 5장 내내
  안 보여야 `NO_FIRE`로 돌아간다 (깜빡임 방지). 1~2장만 보이면 `SUSPECT`.
- 영상이 없거나 오래됐거나(`NO_FRAME`), 추론이 실패하거나(`ERROR`), 모델이 없으면(`NO_MODEL`) "불 값 없음"이다.
  이때 연속 판정은 처음부터 다시 한다.
- 우선순위: 선·LiDAR보다 낮고(`nice 5`, 코어 2만 사용) 스트리밍보다 높다. 초당 `max_fps`(2)장까지만 추론한다 ([timing.md](timing.md)).
- 계속 죽어도 `main.py`는 다른 프로세스를 멈추지 않는다.

공유 값 `/dev/shm/firecar/fire.json`:
```json
{"status": "FIRE", "fire": true, "hits": 4, "window": 5,
 "target": {"x": 0.42, "y": 0.71, "width": 0.08, "height": 0.15, "score": 0.83},
 "seen_ms": 0, "detections": [...], "packet": "c36c01..."}
```
`fire`: `true` 불 확정, `false` 불 없음(또는 아직 SUSPECT), `null` 불 값 없음.

## 불 패킷 v1 (초안, STM32 담당자와 확정 필요)

22바이트, little-endian. 추론할 때마다 (초당 최대 2개). 다른 패킷(`C3 3C`, `C3 4C`, `C3 5C`)과 헤더가 다르다.

| 오프셋 | 크기 | 필드 | 정의 |
|---:|---:|---|---|
| 0 | 2 | Header | `C3 6C` |
| 2 | 1 | Version | `1` |
| 3 | 1 | Status | 아래 표 |
| 4 | 2 | Sequence | uint16 |
| 6 | 2 | X | int16. 불 상자 중심. -1000 왼쪽 끝 ~ 0 중앙 ~ +1000 오른쪽 끝. 없으면 `0x7FFF` |
| 8 | 2 | Y | uint16. 0 화면 위 ~ 1000 아래 (아래일수록 대체로 가깝다). 없으면 `0xFFFF` |
| 10 | 2 | Size | uint16. 상자 넓이, 화면 대비 ‰ (0~1000). 클수록 가깝거나 큰 불. 없으면 `0xFFFF` |
| 12 | 1 | Confidence | 0~100 |
| 13 | 1 | Hits | 최근 Window장 중 불이 보인 장수 |
| 14 | 1 | Window | 연속 판정에 쓰는 장수 (기본 5) |
| 15 | 1 | Candidates | 이번 영상의 불 상자 수 |
| 16 | 2 | Seen | 위치(X·Y·Size)를 측정한 뒤 지난 ms. 이번 영상에서 봤으면 0. 없으면 `0xFFFF` |
| 18 | 2 | Age | 촬영 후 패킷 생성까지 ms. 없으면 `0xFFFF` |
| 20 | 2 | CRC | CRC-16/CCITT-FALSE, 바이트 0~19 |

| Status | 이름 | 뜻 | STM32 처리 |
|---:|---|---|---|
| 0 | `FIRE` | 불 확정 | 소화 동작 판단에 사용 |
| 1 | `NO_FIRE` | 영상은 정상, 불 없음 | 불 없음 |
| 2 | `SUSPECT` | 보였지만 아직 확정 아님 | 불로 취급하지 않음 (접근·감속 정도는 선택) |
| 3 | `NO_FRAME` | 최신 영상 없음 | **불 값 없음** (불 없음 아님) |
| 4 | `ERROR` | 추론 실패 | **불 값 없음** |
| 5 | `NO_MODEL` | 모델 파일 없음 | **불 값 없음** |

- 위치 필드는 `FIRE`·`SUSPECT`일 때만 있다. 이번 영상에서 놓쳤어도 최근 Window 안에 본 위치를 주고, Seen으로 얼마나 지난 값인지 알린다.
- 위치는 화면 기준이다. 실제 각도·거리로 바꾸려면 카메라 화각과 설치 높이·기울기를 재야 한다.
- 나중에 전송 프로그램은 대기 시간을 Age·Seen에 더하고 CRC를 다시 계산해야 하며, 같은 Sequence를 다시 보내지 않는다.

## 파일

| 파일 | 역할 |
|---|---|
| `fire/run.py` | 추론 프로세스 (`main.py`가 띄움) |
| `fire/detector.py` | 전처리, ONNX 추론, 출력 해석 |
| `fire/packet.py` | 불 패킷 v1 |
| `fire/collect.py` | 학습용 사진 저장 |
| `fire/preview.py` | 감지 결과 그림 |
| `fire/config.toml` | 모델 경로, 임계값, 연속 판정, 속도 |
| `fire/models/fire.onnx` | 사용 중인 모델 (지금: rabahdev/fire-smoke-yolov8n, 입력 320) |
| `fire/train/download_dfire.py` | D-Fire 받아서 불만 남긴 YOLO 데이터셋 만들기 |
| `fire/train/colab_train.ipynb` | Colab 학습 노트북 |
| `fire/train/train.sh` | PC(GPU)에서 학습할 때 |
| `fire/train/convert_pretrained.py` | 받은 `.pt` 모델을 안전하게 검사·변환 |
| `fire/train/evaluate.py` | 시험 사진으로 감지율·오탐·속도 측정 |
| `fire/tests/data/dummy_yolo.onnx` | 테스트용 가짜 모델 (항상 화면 가운데 불). `make_dummy_yolo.py`로 만듦 (`pip install onnx` 필요) |
