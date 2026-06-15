#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
업체 좌표 목록을 기준점 거리로 필터링하는 모듈.

tmap_gui.py 가 사용하는 함수/예외를 제공한다.

처리 방식(2단계):
  1) 직선거리(하버사인) x 우회계수 로 1차 스크리닝
     - 실제 도로거리는 직선거리보다 길기 때문에 (직선거리 x 우회계수)가
       기준 거리를 넘으면 API 호출 없이 제외한다. (API 호출량 절감)
  2) 1차 통과분만 TMAP 화물차 경로 API로 실제 거리/시간을 조회하고,
     실제 도로거리가 기준 거리 이내인 업체만 결과에 남긴다.

좌표 변환(geocode)과 경로 조회(get_route)는 tmap_distance 모듈을 재사용한다.
"""

import csv
import math
import os

# tmap_distance 의 기능을 재사용한다.
from tmap_distance import (
    TmapError,
    geocode,
    get_route,
    format_duration,
)

__all__ = ["TmapError", "geocode", "get_route", "process_file", "haversine"]


def haversine(origin, dest):
    """두 (위도, 경도) 사이의 직선거리(km)를 반환한다."""
    lat1, lon1 = origin
    lat2, lon2 = dest
    r = 6371.0  # 지구 반경(km)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _read_rows(path):
    """CSV 를 인코딩 자동 감지하여 (행 리스트, 컬럼명) 으로 반환."""
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                rows = [dict(r) for r in reader]
                fields = reader.fieldnames
            if rows:
                return rows, fields
        except (UnicodeDecodeError, LookupError):
            continue
    raise TmapError(f"CSV 인코딩을 인식할 수 없습니다: {path}")


def _pick(row, *candidates):
    for key in candidates:
        if key in row and row[key] not in (None, ""):
            return row[key].strip()
    return ""


def _float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _output_name(input_path, max_km):
    """입력 파일명에서 결과 파일명을 만든다. 예: 콘크리트_50km이내.csv"""
    base = os.path.basename(input_path)
    if "콘크리트" in base:
        prefix = "콘크리트"
    elif "아스콘" in base:
        prefix = "아스콘"
    else:
        prefix = os.path.splitext(base)[0]
    km = int(max_km) if float(max_km).is_integer() else max_km
    return f"{prefix}_{km}km이내.csv"


def process_file(input_path, origin, max_km, app_key, session, buffer=1.2):
    """
    input_path 의 업체 목록을 기준점(origin)에서 max_km 이내로 필터링하여
    결과 CSV 를 같은 폴더에 저장한다.

    Parameters
    ----------
    input_path : str   업체 좌표 CSV (컬럼: 업체명, 주소/공장사업장주소, 위도, 경도)
    origin     : tuple (위도, 경도) 기준점
    max_km     : float 기준 거리(km)
    app_key    : str   TMAP APP KEY
    session    : requests.Session
    buffer     : float 우회계수 (직선거리 x buffer 로 1차 스크리닝)
    """
    rows, _ = _read_rows(input_path)
    name = os.path.basename(input_path)
    print(f"\n[{name}] 총 {len(rows)}건 처리 시작 (기준 {max_km}km, 우회계수 {buffer})")

    # 1차 스크리닝: 직선거리 x 우회계수
    screened = []
    skipped_no_coord = 0
    for row in rows:
        lat = _float(_pick(row, "위도", "lat"))
        lon = _float(_pick(row, "경도", "lon"))
        if lat is None or lon is None:
            skipped_no_coord += 1
            continue
        straight = haversine(origin, (lat, lon))
        if straight * buffer <= max_km:
            screened.append((row, lat, lon, straight))

    print(f"  1차 통과(직선거리 기준): {len(screened)}건 "
          f"(좌표 없음 {skipped_no_coord}건 제외)")

    # 2차: 실제 도로거리/시간 조회
    results = []
    for idx, (row, lat, lon, straight) in enumerate(screened, 1):
        company = _pick(row, "업체명", "name")
        addr = _pick(row, "주소", "공장사업장주소", "address")
        try:
            dist_m, dur_s = get_route(origin, (lat, lon), app_key, session)
            road_km = round(dist_m / 1000, 2)
        except TmapError as exc:
            print(f"  [{idx}/{len(screened)}] {company}: 경로 실패 ({exc})")
            continue

        if road_km <= max_km:
            results.append({
                "업체명": company,
                "주소": addr,
                "위도": lat,
                "경도": lon,
                "직선거리(km)": round(straight, 2),
                "도로거리(km)": road_km,
                "예상시간": format_duration(dur_s),
            })
            print(f"  [{idx}/{len(screened)}] {company}: "
                  f"{road_km}km, {format_duration(dur_s)} ✓")

    # 결과 저장
    out_path = os.path.join(os.path.dirname(input_path), _output_name(input_path, max_km))
    fields = ["업체명", "주소", "위도", "경도", "직선거리(km)", "도로거리(km)", "예상시간"]
    # 가까운 순으로 정렬
    results.sort(key=lambda r: r["도로거리(km)"])
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)

    print(f"  => 최종 {len(results)}건 (도로거리 {max_km}km 이내) 저장: "
          f"{os.path.basename(out_path)}")
    return out_path
