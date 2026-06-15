# TMAP 거리·시간 조회

기준 위치에서 여러 목적지까지의 **이동 거리**와 **예상 이동시간**을 TMAP API로 조회하는 프로그램입니다.

- 주소 → 좌표 변환: TMAP **전체주소 지오코딩**(`/tmap/geo/fullAddrGeo`)
- 거리/시간 조회: TMAP **화물차 경로안내**(`/tmap/truck/routes`)

## 1. 설치

```bash
pip install -r requirements.txt
```

## 2. 설정

`config_example.py` 를 `config.py` 로 복사하고 값을 채웁니다.
(`config.py` 는 `.gitignore` 처리되어 저장소에 올라가지 않습니다.)

```bash
cp config_example.py config.py
```

`config.py` 에서 설정할 값:

| 항목 | 설명 |
| --- | --- |
| `APP_KEY` | SK open API 프로젝트에서 발급받은 APP KEY |
| `ORIGIN_ADDRESS` | **기준 위치(출발지) 주소** — 통문장으로 입력 |
| `TRUCK_*` | 화물차 제원(폭/높이/중량/길이/차종). 화물차 경로 API 필수값. 기본은 20ton 트럭으로 설정되어있음 |

> 화물차 경로안내 API는 차량 제원이 필수이므로 기본값이 들어 있습니다.
> 실제 차량에 맞게 조정하세요.

## 3. 입력 CSV

`업체명, 주소` 두 컬럼이 필요합니다. (인코딩은 UTF-8 / CP949(euc-kr) 자동 감지)

```csv
업체명,주소
(주)원클린,경기도 이천시 부발읍 부발중앙로 85
```

## 4. 실행

```bash
python tmap_distance.py                 # config.py 설정값 사용
python tmap_distance.py -i my.csv -o result.csv
python tmap_distance.py --origin "서울특별시 중구 세종대로 110"
```

## 5. 출력

`output.csv` (UTF-8 BOM, Excel 호환) 와 콘솔에 출력됩니다.

| 업체명 | 주소 | 위도 | 경도 | 거리(km) | 예상시간 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |

- **거리(km)**: 경로 총 거리
- **예상시간**: 실시간 교통 기준 예상 소요 시간 (`1시간 23분` 형식)
- **상태**: 성공 / 실패 사유
