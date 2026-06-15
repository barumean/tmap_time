# -*- coding: utf-8 -*-
"""
설정 템플릿. (차량 제원/기준주소 등)
이 파일을 config.py 로 복사한 뒤 값을 채워 넣으세요.

    cp config_example.py config.py

※ APP KEY 는 여기에 넣지 않습니다. 프로그램 실행 시 직접 입력합니다.
"""

# 기준 위치(출발지) 주소 - 통문장 그대로 입력 (GUI/CLI 의 기본값으로 쓰임, 선택)
ORIGIN_ADDRESS = "여기에_기준위치_주소_입력"

# 입출력 CSV 경로 (CLI 인자 -i / -o 로 덮어쓸 수 있음)
INPUT_CSV = "input.csv"
OUTPUT_CSV = "output.csv"

# API 호출 간 지연(초). 과도한 호출/레이트리밋 방지용.
REQUEST_DELAY = 0.2

# ----- 화물차 제원 (truck/routes API 필수값) : 20톤 덤프트럭 기준 -----
# truckType: 1 화물자동차, 2 건설기계, 3 특수자동차, 4 위험물,
#            5 승용/소형, 6 중형승합, 7 대형승합
TRUCK_TYPE = 1
TRUCK_WIDTH = 250          # 차폭 (cm, 100~300) - 법정 최대
TRUCK_HEIGHT = 330         # 높이 (cm, 100~600)
TRUCK_WEIGHT = 20000       # 적재중량 (kg, 500~40000) - 20톤
TRUCK_TOTAL_WEIGHT = 33000  # 총중량 (kg, 500~40000) - 자체중량 약 13t + 적재 20t
TRUCK_LENGTH = 800         # 길이 (cm, 200~4000)
