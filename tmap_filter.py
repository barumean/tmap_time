#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
기준 주소에서 일정 거리(예: 50km) 이내의 업체만 골라내는 프로그램.

2단계로 동작한다.
  1) 1차 스크리닝(무료/즉시): 위경도로 기준점과의 직선거리(Haversine)를 구하고
     우회계수(기본 1.2배)를 곱해 도로거리를 추정한다.
     '직선거리 x 1.2 > 기준거리'인 곳은 먼저 제거 → API 호출이 확 줄어 빠르다.
  2) 2차 정밀(API): 1차 통과분에만 TMAP 화물차 경로 API로 실제 도로거리/시간 조회.

결과 CSV 컬럼: 업체명, 주소, 거리(km), 시간   (+직선거리(km) 참고)
APP KEY 는 실행 시 직접 입력받는다(--app-key 인자 또는 프롬프트).
차량 제원은 config.py 를 사용한다.

사용 예:
    python tmap_filter.py --origin "부산 강서구 평강로 271" --max-km 50
    python tmap_filter.py --origin "부산 ..." --max-km 50 --buffer 1.3
    python tmap_filter.py --origin-latlon 35.16,128.99 --max-km 30
    python tmap_filter.py --app-key 발급받은키 --origin "부산 ..." --max-km 50
"""

import argparse
import csv
import math
import os
import sys
import time

import requests

try:
    import config
except ImportError:
    sys.exit("[오류] config.py 가 없습니다. config_example.py 를 복사해 차량 제원을 설정하세요.")


def resolve_app_key(cli_value):
    """APP KEY 를 직접 입력받는다. 인자가 없으면 실행 중 입력을 요청한다."""
    key = (cli_value or "").strip()
    if not key:
        try:
            key = input("TMAP APP KEY 입력: ").strip()
        except EOFError:
            key = ""
    if not key:
        sys.exit("[오류] APP KEY 가 필요합니다. --app-key 로 전달하거나 실행 시 입력하세요.")
    return key

GEOCODE_URL = "https://apis.openapi.sk.com/tmap/geo/fullAddrGeo"
TRUCK_ROUTE_URL = "https://apis.openapi.sk.com/tmap/truck/routes"

DEFAULT_INPUTS = ["콘크리트_업체_좌표.csv", "아스콘_업체_좌표.csv"]
ADDR_CANDIDATES = ("주소", "공장사업장주소", "address", "addr")


class TmapError(Exception):
    pass


def _first_float(*values):
    for v in values:
        if v not in (None, "", "0", "0.0"):
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def format_duration(seconds):
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h}시간 {m}분" if h else f"{m}분"


def geocode(full_addr, app_key, session, retries=3):
    params = {
        "version": "1", "format": "json", "coordType": "WGS84GEO",
        "fullAddr": full_addr, "appKey": app_key,
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
        coords = (data.get("coordinateInfo", {}).get("coordinate")) or []
        if not coords:
            raise TmapError("좌표 결과 없음 (주소 매칭 실패)")
        c = coords[0]
        lat = _first_float(c.get("newLat"), c.get("lat"))
        lon = _first_float(c.get("newLon"), c.get("lon"))
        if lat is None or lon is None:
            raise TmapError("좌표 값이 비어 있음")
        return lat, lon
    raise TmapError(f"지오코딩 요청 실패: {last_err}")


def _extract_total(data):
    if "features" in data:
        for feat in data["features"]:
            props = feat.get("properties", {})
            if "totalDistance" in props and "totalTime" in props:
                return props.get("totalDistance"), props.get("totalTime")
    props = data.get("properties", data)
    if "totalDistance" in props and "totalTime" in props:
        return props.get("totalDistance"), props.get("totalTime")
    return None, None


def get_route(start, end, app_key, session, retries=3):
    payload = {
        "startX": str(start[1]), "startY": str(start[0]),
        "endX": str(end[1]), "endY": str(end[0]),
        "reqCoordType": "WGS84GEO", "resCoordType": "WGS84GEO",
        "searchOption": "17", "totalValue": "2",
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
            resp = session.post(TRUCK_ROUTE_URL, params={"version": "1"},
                                json=payload, headers=headers, timeout=15)
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


def read_csv(path):
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                text = f.read().replace("\x00", "")
            reader = csv.DictReader(text.splitlines())
            rows = [dict(r) for r in reader]
            if rows:
                return rows, list(reader.fieldnames)
        except (UnicodeDecodeError, LookupError):
            continue
    raise SystemExit(f"[오류] CSV 인코딩 인식 실패: {path}")


def pick_addr_col(fieldnames):
    for k in ADDR_CANDIDATES:
        if k in fieldnames:
            return k
    return None


def out_path(input_path, max_km):
    base = os.path.splitext(os.path.basename(input_path))[0]
    base = base.replace("_업체_좌표", "").replace("_좌표", "")
    return f"{base}_{int(max_km)}km이내.csv"


def process_file(input_path, origin, max_km, app_key, session, buffer=1.2):
    rows, fieldnames = read_csv(input_path)
    addr_col = pick_addr_col(fieldnames)
    if not addr_col:
        print(f"[건너뜀] {input_path}: 주소 컬럼 없음 {fieldnames}")
        return

    total = len(rows)
    no_coord = 0
    candidates = []
    for row in rows:
        lat = _first_float(row.get("위도"))
        lon = _first_float(row.get("경도"))
        if lat is None or lon is None:
            no_coord += 1
            continue
        d = haversine_km(origin[0], origin[1], lat, lon)
        if d * buffer <= max_km:
            candidates.append((row, addr_col, lat, lon, d))

    print(f"\n=== {input_path} ===")
    print(f"  전체 {total} | 좌표없음 {no_coord} | "
          f"1차통과(직선x{buffer} <= {max_km}km, 직선 {round(max_km / buffer, 1)}km 이내) "
          f"{len(candidates)} -> API 호출 {len(candidates)}건")

    results = []
    for i, (row, ac, lat, lon, straight) in enumerate(candidates, 1):
        name = (row.get("업체명") or "").strip()
        addr = (row.get(ac) or "").strip()
        road_km = ""
        dur_text = ""
        status = "성공"
        try:
            dist_m, dur_s = get_route(origin, (lat, lon), app_key, session)
            road_km = round(dist_m / 1000, 2)
            dur_text = format_duration(dur_s)
        except TmapError as exc:
            status = f"실패: {exc}"
        results.append({
            "업체명": name,
            "주소": addr,
            "거리(km)": road_km,
            "시간": dur_text,
            "직선거리(km)": round(straight, 2),
            "상태": status,
        })
        if i % 20 == 0 or i == len(candidates):
            print(f"  경로조회 {i}/{len(candidates)}")
        time.sleep(getattr(config, "REQUEST_DELAY", 0.2))

    final = [r for r in results
             if r["상태"] == "성공" and r["거리(km)"] != "" and r["거리(km)"] <= max_km]
    over = [r for r in results
            if r["상태"] == "성공" and r["거리(km)"] != "" and r["거리(km)"] > max_km]
    failed = [r for r in results if r["상태"] != "성공"]
    final.sort(key=lambda r: r["거리(km)"])

    op = out_path(input_path, max_km)
    fields = ["업체명", "주소", "거리(km)", "시간", "직선거리(km)"]
    with open(op, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(final)

    print(f"  도로거리 {max_km}km 이내 최종 {len(final)}건 -> {op}")
    if over:
        print(f"  (직선x{buffer}는 통과했으나 도로거리 초과 {len(over)}건 제외)")
    if failed:
        print(f"  (API 실패 {len(failed)}건 - 네트워크/주소 확인 필요)")
    return op


def main():
    p = argparse.ArgumentParser(description="기준 주소에서 N km 이내 업체 필터(직선x1.2 1차 + 경로 API 2차)")
    p.add_argument("-i", "--input", action="append", help="좌표 CSV (여러 번 지정 가능)")
    p.add_argument("--origin", default=getattr(config, "ORIGIN_ADDRESS", None),
                   help="기준 주소 (지오코딩). 미지정 시 config.ORIGIN_ADDRESS")
    p.add_argument("--origin-latlon", default=None,
                   help="기준 좌표 'lat,lon' 직접 지정(지오코딩 생략)")
    p.add_argument("--max-km", type=float, default=50.0, help="기준 거리(km), 기본 50")
    p.add_argument("--buffer", type=float, default=1.2,
                   help="직선거리 우회계수(1차 스크리닝). 기본 1.2")
    p.add_argument("--app-key", default=None,
                   help="TMAP APP KEY (미지정 시 실행 중 직접 입력)")
    args = p.parse_args()

    app_key = resolve_app_key(args.app_key)

    session = requests.Session()

    if args.origin_latlon:
        try:
            la, lo = [float(x) for x in args.origin_latlon.split(",")]
            origin = (la, lo)
            print(f"기준점(좌표 지정): 위도 {la}, 경도 {lo}")
        except ValueError:
            sys.exit("[오류] --origin-latlon 형식은 'lat,lon' (예: 35.16,128.99)")
    else:
        if not args.origin or args.origin.startswith("여기에"):
            sys.exit("[오류] 기준 주소를 --origin 또는 config.ORIGIN_ADDRESS 로 지정하세요.")
        try:
            origin = geocode(args.origin, app_key, session)
        except TmapError as exc:
            sys.exit(f"[오류] 기준 주소 지오코딩 실패: {args.origin} ({exc})")
        print(f"기준점: {args.origin} -> 위도 {origin[0]}, 경도 {origin[1]}")

    inputs = args.input or DEFAULT_INPUTS
    for path in inputs:
        if not os.path.exists(path):
            print(f"[건너뜀] 파일 없음: {path}")
            continue
        process_file(path, origin, args.max_km, app_key, session, args.buffer)


if __name__ == "__main__":
    main()
