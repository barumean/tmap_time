#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
기준 위치에서 여러 목적지까지의 거리와 예상 이동시간을 TMAP API로 조회하는 프로그램.

처리 흐름:
  1. CSV(업체명, 주소)를 읽는다.
  2. 전체주소 지오코딩(fullAddrGeo)으로 각 주소를 위경도 좌표로 변환한다.
  3. 화물차 경로안내(truck/routes) API로 기준 위치 -> 목적지 거리/시간을 조회한다.
  4. 결과를 CSV와 콘솔로 출력한다.

설정(APP KEY, 기준 위치, 차량 제원 등)은 config.py 에 분리되어 있다.
"""

import argparse
import csv
import sys
import time
from urllib.parse import quote

import requests

try:
    import config
except ImportError:
    sys.exit(
        "[오류] config.py 가 없습니다. config_example.py 를 config.py 로 복사한 뒤 "
        "APP_KEY 와 기준 위치를 입력하세요."
    )

GEOCODE_URL = "https://apis.openapi.sk.com/tmap/geo/fullAddrGeo"
TRUCK_ROUTE_URL = "https://apis.openapi.sk.com/tmap/truck/routes"


class TmapError(Exception):
    """TMAP API 호출 중 발생한 오류."""


def geocode(full_addr, app_key, session, retries=3):
    """전체주소 문자열을 (위도, 경도) 로 변환한다. 실패 시 TmapError."""
    params = {
        "version": "1",
        "format": "json",
        "coordType": "WGS84GEO",
        "fullAddr": full_addr,
        "appKey": app_key,
    }
    last_err = None
    for attempt in range(retries):
        try:
            resp = session.get(GEOCODE_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            last_err = exc
            time.sleep(2 ** attempt * 0.5)
            continue

        info = data.get("coordinateInfo", {})
        coords = info.get("coordinate") or []
        if not coords:
            raise TmapError("좌표 결과 없음 (주소 매칭 실패)")

        c = coords[0]
        # 도로명 매칭(newLat/newLon)이 있으면 우선 사용, 없으면 지번 좌표(lat/lon).
        lat = _first_float(c.get("newLat"), c.get("lat"))
        lon = _first_float(c.get("newLon"), c.get("lon"))
        if lat is None or lon is None:
            raise TmapError("좌표 값이 비어 있음")
        return lat, lon

    raise TmapError(f"지오코딩 요청 실패: {last_err}")


def _first_float(*values):
    """비어 있지 않은 첫 값을 float 으로 반환. 없으면 None."""
    for v in values:
        if v not in (None, "", "0", "0.0"):
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def get_route(start, end, app_key, session, retries=3):
    """기준 위치(start) -> 목적지(end) 화물차 경로의 (거리 m, 시간 초) 반환."""
    start_lat, start_lon = start
    end_lat, end_lon = end

    payload = {
        "startX": str(start_lon),
        "startY": str(start_lat),
        "endX": str(end_lon),
        "endY": str(end_lat),
        "reqCoordType": "WGS84GEO",
        "resCoordType": "WGS84GEO",
        "searchOption": "17",          # 교통최적 + 화물차 (화물차 단일 옵션)
        "totalValue": "2",             # 총거리/총시간/요금 정보만 응답
        "truckType": str(config.TRUCK_TYPE),
        "truckWidth": str(config.TRUCK_WIDTH),
        "truckHeight": str(config.TRUCK_HEIGHT),
        "truckWeight": str(config.TRUCK_WEIGHT),
        "truckTotalWeight": str(config.TRUCK_TOTAL_WEIGHT),
        "truckLength": str(config.TRUCK_LENGTH),
    }
    headers = {"appKey": app_key, "Content-Type": "application/json"}

    last_err = None
    for attempt in range(retries):
        try:
            resp = session.post(
                TRUCK_ROUTE_URL,
                params={"version": "1"},
                json=payload,
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            last_err = exc
            time.sleep(2 ** attempt * 0.5)
            continue

        dist, dur = _extract_total(data)
        if dist is None or dur is None:
            raise TmapError("경로 응답에서 거리/시간을 찾지 못함")
        return dist, dur

    raise TmapError(f"경로 요청 실패: {last_err}")


def _extract_total(data):
    """경로 응답에서 총거리(m), 총시간(초)을 추출한다."""
    # totalValue=2 응답 형태가 버전에 따라 다를 수 있어 두 경우 모두 대응한다.
    if "features" in data:
        for feat in data["features"]:
            props = feat.get("properties", {})
            if "totalDistance" in props and "totalTime" in props:
                return props.get("totalDistance"), props.get("totalTime")
    # 평탄한 dict 형태(예: {"properties": {...}} 또는 최상위에 값) 대응
    props = data.get("properties", data)
    if "totalDistance" in props and "totalTime" in props:
        return props.get("totalDistance"), props.get("totalTime")
    return None, None


def read_input(path):
    """CSV(업체명, 주소)를 읽어 dict 리스트로 반환. 인코딩 자동 감지."""
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                rows = [dict(r) for r in reader]
            if rows:
                return rows, reader.fieldnames
        except (UnicodeDecodeError, LookupError):
            continue
    raise SystemExit(f"[오류] CSV 인코딩을 인식할 수 없습니다: {path}")


def pick(row, *candidates):
    """행에서 후보 컬럼명 중 존재하는 값을 반환."""
    for key in candidates:
        if key in row and row[key]:
            return row[key].strip()
    return ""


def format_duration(seconds):
    """초 -> '1시간 23분' 형태 문자열."""
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h:
        return f"{h}시간 {m}분"
    return f"{m}분"


def main():
    parser = argparse.ArgumentParser(
        description="TMAP API로 기준 위치에서 여러 목적지까지 거리/예상시간 조회"
    )
    parser.add_argument(
        "-i", "--input", default=getattr(config, "INPUT_CSV", "input.csv"),
        help="입력 CSV 경로 (컬럼: 업체명, 주소)",
    )
    parser.add_argument(
        "-o", "--output", default=getattr(config, "OUTPUT_CSV", "output.csv"),
        help="결과 CSV 경로",
    )
    parser.add_argument(
        "--origin", default=None,
        help="기준 위치 주소 (미지정 시 config.ORIGIN_ADDRESS 사용)",
    )
    args = parser.parse_args()

    app_key = config.APP_KEY
    if not app_key or app_key.startswith("여기에"):
        sys.exit("[오류] config.py 의 APP_KEY 를 설정하세요.")

    origin_addr = args.origin or config.ORIGIN_ADDRESS
    if not origin_addr or origin_addr.startswith("여기에"):
        sys.exit("[오류] 기준 위치를 config.ORIGIN_ADDRESS 또는 --origin 으로 설정하세요.")

    session = requests.Session()

    # 1) 기준 위치 좌표 변환
    try:
        origin = geocode(origin_addr, app_key, session)
    except TmapError as exc:
        sys.exit(f"[오류] 기준 위치 지오코딩 실패: {origin_addr} ({exc})")
    print(f"기준 위치: {origin_addr} -> 위도 {origin[0]}, 경도 {origin[1]}\n")

    rows, _ = read_input(args.input)

    results = []
    for row in rows:
        name = pick(row, "업체명", "name", "이름")
        addr = pick(row, "주소", "address", "addr")
        if not addr:
            continue

        status = "성공"
        lat = lon = dist_km = dur_text = ""
        try:
            dest = geocode(addr, app_key, session)
            lat, lon = dest
            dist_m, dur_s = get_route(origin, dest, app_key, session)
            dist_km = round(dist_m / 1000, 2)
            dur_text = format_duration(dur_s)
        except TmapError as exc:
            status = f"실패: {exc}"

        print(f"- {name or addr}: {dist_km} km, {dur_text}  [{status}]")
        results.append({
            "업체명": name,
            "주소": addr,
            "위도": lat,
            "경도": lon,
            "거리(km)": dist_km,
            "예상시간": dur_text,
            "상태": status,
        })
        time.sleep(getattr(config, "REQUEST_DELAY", 0.2))

    fieldnames = ["업체명", "주소", "위도", "경도", "거리(km)", "예상시간", "상태"]
    with open(args.output, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"\n완료: {len(results)}건 -> {args.output}")


if __name__ == "__main__":
    main()
