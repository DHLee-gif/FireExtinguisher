# 선 패킷 v2 (초안, STM32 담당자와 확정 필요)

25바이트, little-endian. 15회/초 (`line/config.toml` `max_fps`, 이유는 [timing.md](timing.md)). LiDAR 패킷(`C3 3C`, `C3 5C`)과 헤더가 다르다.

| 오프셋 | 크기 | 필드 | 정의 |
|---:|---:|---|---|
| 0 | 2 | Header | `C3 4C` |
| 2 | 1 | Version | `2` |
| 3 | 1 | Status | 0 선 있음, 1 선 없음, 2 최신 영상 없음, 3 처리 오류 |
| 4 | 2 | Sequence | uint16 |
| 6 | 2 | Offset | int16, 이번 영상 값. -1000 왼쪽 끝 ~ 0 중앙 ~ +1000 오른쪽 끝 |
| 8 | 2 | Angle | int16, 0.01도. 화면 기준, + 는 앞쪽이 오른쪽으로 기움 |
| 10 | 2 | Smooth offset | int16, 노이즈를 줄인 치우침 (Offset과 같은 단위) |
| 12 | 2 | Smooth angle | int16, 노이즈를 줄인 각도 (0.01도) |
| 14 | 2 | Offset rate | int16, 치우침 변화 속도, 1000 = 화면 반 폭/초. + 는 오른쪽으로 이동 중 |
| 16 | 1 | Confidence | 0~100 |
| 17 | 1 | Candidates | 보이는 선 후보 수, 2 이상이면 애매함 |
| 18 | 1 | Last side | int8, 마지막으로 본 선 위치: -1 왼쪽, 0 가운데, +1 오른쪽. 선을 놓쳤을 때 찾을 방향 |
| 19 | 2 | Lost | 마지막으로 선을 본 뒤 ms. 지금 보이면 0. 본 적 없으면 `0xFFFF` |
| 21 | 2 | Age | 촬영 후 패킷 생성까지 ms. 없으면 `0xFFFF` |
| 23 | 2 | CRC | CRC-16/CCITT-FALSE, 바이트 0~22 |

- **조향에는 Status 0일 때만 Smooth 값과 Offset rate를 쓴다.** 선이 갑자기 튀어 Status 1이 되어도 Smooth 값은 0.5초 동안 이전 값을 유지하기 때문이다.
- 선을 처음 찾은 프레임의 Offset rate는 `0x7FFF`이고, 다음 1~2번(15Hz에서 약 67~133 ms)은 실제보다 작게 나온다.
- Offset, Angle은 Status 0일 때만 값이 있고 아니면 `0x7FFF`.
- Smooth offset, Smooth angle, Offset rate는 0.5초 안에 본 선이 있으면 선을 잠깐 놓쳐도 마지막 값을 유지하고, 그보다 오래되면 `0x7FFF`.
- Age가 한도(Pi 기본 200 ms)를 넘거나 새 Sequence가 오지 않으면 쓰지 않는다. 나중에 만들 전송 프로그램은 대기 시간을 Age에 더해야 한다.
- 값은 화면 기준이다. 실제 거리(mm)로 바꾸려면 카메라 높이와 기울기를 재야 한다.
