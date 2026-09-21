#!/usr/bin/env python3
"""상권나우 신규/소멸 점포 전량 PMTiles 빌드 스크립트.

`scripts/build-data.py` 와 같은 원천(소진공 상가(상권)정보 분기 스냅샷 zip 2개)을
같은 규칙(상가업소번호 diff, 이전 분기는 RegionRemapper 로 시군구/행정동 코드 보정)
으로 다시 읽어서, `public/data/changes/*.json` 표본(시군구당 ~1,000+1,000) 대신
**신규/소멸 점포 전량**을 NDJSON GeoJSON Feature 스트림으로 스크래치에 쓴다.
그 다음 tippecanoe 로 `public/tiles/changes.pmtiles` 를 만든다.

표준 라이브러리만 사용(대용량 스트리밍: zipfile + csv, 메모리에 전체를 올리지 않음).
build-data.py 와 달리 diff 를 위해 각 분기 store_id 집합만 메모리에 유지하면 되므로
레코드 자체는 스트리밍 중에 바로 파일로 흘려보낸다 — 단, 신규(diff)는 "최신에만 있는
id" 를 알아야 하므로 이전 분기 id 집합을 먼저 모두 읽어야 한다. 아래 2-pass 구조:

  1) 이전 분기를 스트리밍하며 store_id 집합만 저장(레코드는 버림) — 메모리: set[str] 하나.
     동시에 이전 분기 레코드를 임시 NDJSON(제자리)으로 한 번 더 스트리밍 저장하지 않고,
     "소멸" 판정을 위해 필요한 (레코드, id) 를 그때그때 판단할 수 없으므로 아래처럼 처리:
     - 최신 분기 store_id 집합을 먼저 만든다(reader 1회).
     - 이전 분기를 스트리밍하며, id 가 "최신 집합에 없으면"(=소멸) 그 자리에서 바로
       GeoJSON Feature 로 써버린다. 레코드를 메모리에 쌓지 않는다.
     - 최신 분기를 다시 스트리밍하며, id 가 "이전 집합에 없으면"(=신규) 바로 써버린다.
  이러면 메모리에는 store_id 문자열 집합 두 개(각 ~270만~280만 개)만 있으면 된다.

사용법:
    python3 scripts/build-tiles.py \
        --current-zip <202606 zip> --previous-zip <202506 zip> \
        --ndjson <스크래치>/changes.ndjson
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from region_remap import RegionRemapper, build_cur_dong_index, load_region_map  # noqa: E402

COLUMNS = [
    "상가업소번호", "상호명", "지점명", "상권업종대분류코드", "상권업종대분류명",
    "상권업종중분류코드", "상권업종중분류명", "상권업종소분류코드", "상권업종소분류명",
    "표준산업분류코드", "표준산업분류명", "시도코드", "시도명", "시군구코드", "시군구명",
    "행정동코드", "행정동명", "법정동코드", "법정동명", "지번코드", "대지구분코드",
    "대지구분명", "지번본번지", "지번부번지", "지번주소", "도로명코드", "도로명",
    "건물본번지", "건물부번지", "건물관리번호", "건물명", "도로명주소", "구우편번호",
    "신우편번호", "동정보", "층정보", "호정보", "경도", "위도",
]
IDX = {name: i for i, name in enumerate(COLUMNS)}

ID = IDX["상가업소번호"]
NAME = IDX["상호명"]
BRANCH = IDX["지점명"]
MID_NAME = IDX["상권업종중분류명"]
SIGUNGU_CODE = IDX["시군구코드"]
DONG_NAME = IDX["행정동명"]
DONG_CODE = IDX["행정동코드"]
JIBUN_ADDR = IDX["지번주소"]
ROAD_ADDR = IDX["도로명주소"]
LON = IDX["경도"]
LAT = IDX["위도"]

KR_LAT_RANGE = (32.5, 39.5)
KR_LON_RANGE = (124.0, 132.5)


def iter_rows(zip_path: Path):
    """zip 안의 csv 를 스트리밍으로 순회(build-data.py 와 동일한 컬럼 검증)."""
    with zipfile.ZipFile(zip_path) as z:
        csv_members = sorted(n for n in z.namelist() if n.lower().endswith(".csv"))
        if not csv_members:
            raise SystemExit(f"[build-tiles] {zip_path} 안에 csv 파일이 없습니다")
        for member in csv_members:
            with z.open(member) as raw:
                tf = io.TextIOWrapper(raw, encoding="utf-8", newline="")
                reader = csv.reader(tf)
                header = next(reader)
                if len(header) != len(COLUMNS):
                    print(
                        f"[build-tiles][경고] {member} 헤더 컬럼 수 {len(header)} != {len(COLUMNS)}",
                        file=sys.stderr,
                    )
                for row in reader:
                    if len(row) != len(COLUMNS):
                        continue
                    yield row


def collect_ids(zip_path: Path) -> set[str]:
    ids = set()
    for row in iter_rows(zip_path):
        ids.add(row[ID])
    return ids


def collect_dong_meta(zip_path: Path) -> dict[str, dict[str, str]]:
    """{시군구코드: {행정동명: 행정동코드}} — RegionRemapper 용(build_cur_dong_index 입력)."""
    dong_meta: dict[str, tuple[str, str]] = {}
    for row in iter_rows(zip_path):
        dong_meta.setdefault(iv(row[DONG_CODE]), (iv(row[SIGUNGU_CODE]), iv(row[DONG_NAME])))
    return dong_meta


def iv(s: str):
    return sys.intern(s) if s else s


def parse_coord(lon_raw: str, lat_raw: str):
    if not lon_raw or not lat_raw:
        return None, None
    try:
        lon = round(float(lon_raw), 6)
        lat = round(float(lat_raw), 6)
    except ValueError:
        return None, None
    if not (KR_LAT_RANGE[0] <= lat <= KR_LAT_RANGE[1]) or not (
        KR_LON_RANGE[0] <= lon <= KR_LON_RANGE[1]
    ):
        return None, None
    return lon, lat


def make_feature(row: list[str], k: int, sigungu_code: str) -> str:
    name = row[NAME]
    branch = row[BRANCH]
    n = f"{name} {branch}" if branch else name
    road = row[ROAD_ADDR] or row[JIBUN_ADDR]
    lon, lat = parse_coord(row[LON], row[LAT])
    if lon is None:
        return None
    props = {
        "k": k,
        "n": n,
        "u": row[MID_NAME],
        "d": row[DONG_NAME],
        "r": road,
        "s": sigungu_code,
    }
    import json

    feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": props,
    }
    return json.dumps(feature, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--current-zip", required=True, type=Path)
    ap.add_argument("--previous-zip", required=True, type=Path)
    ap.add_argument("--ndjson", required=True, type=Path)
    ap.add_argument(
        "--region-map", type=Path,
        default=Path(__file__).resolve().parent / "region-code-map.json",
    )
    args = ap.parse_args()

    print(f"[build-tiles] 최신 분기 id 집합 수집: {args.current_zip}")
    cur_ids = collect_ids(args.current_zip)
    print(f"  -> {len(cur_ids):,} ids")

    print(f"[build-tiles] 최신 분기 행정동 인덱스 수집(remap 용): {args.current_zip}")
    cur_dong_meta = collect_dong_meta(args.current_zip)
    cur_dong_by_sigungu = build_cur_dong_index(cur_dong_meta)
    region_map = load_region_map(args.region_map)
    remapper = RegionRemapper(region_map, cur_dong_by_sigungu)

    print(f"[build-tiles] 이전 분기 id 집합 수집: {args.previous_zip}")
    prev_ids = collect_ids(args.previous_zip)
    print(f"  -> {len(prev_ids):,} ids")

    args.ndjson.parent.mkdir(parents=True, exist_ok=True)

    opened_written = closed_written = 0
    opened_dropped = closed_dropped = 0

    with args.ndjson.open("w", encoding="utf-8") as out:
        print("[build-tiles] 이전 분기 스트리밍 -> 소멸(closed, k=0) 판정")
        for row in iter_rows(args.previous_zip):
            store_id = row[ID]
            if store_id in cur_ids:
                continue  # 공통 id: 소멸 아님
            sigungu_code = row[SIGUNGU_CODE]
            dong_name = row[DONG_NAME]
            dong_code = row[DONG_CODE]
            if remapper.is_affected(sigungu_code):
                new_sigungu_code = remapper.resolve_sigungu(sigungu_code, dong_name)
                sigungu_code = new_sigungu_code
            feature_line = make_feature(row, 0, sigungu_code)
            if feature_line is None:
                closed_dropped += 1
                continue
            out.write(feature_line)
            out.write("\n")
            closed_written += 1

        print("[build-tiles] 최신 분기 스트리밍 -> 신규(opened, k=1) 판정")
        for row in iter_rows(args.current_zip):
            store_id = row[ID]
            if store_id in prev_ids:
                continue  # 공통 id: 신규 아님
            sigungu_code = row[SIGUNGU_CODE]
            feature_line = make_feature(row, 1, sigungu_code)
            if feature_line is None:
                opened_dropped += 1
                continue
            out.write(feature_line)
            out.write("\n")
            opened_written += 1

    print("\n=== 요약 ===")
    print(f"opened: written={opened_written:,} dropped(좌표 결측/이상치)={opened_dropped:,}")
    print(f"closed: written={closed_written:,} dropped(좌표 결측/이상치)={closed_dropped:,}")
    print(f"총 피처 수: {opened_written + closed_written:,}")
    print(f"NDJSON: {args.ndjson}")


if __name__ == "__main__":
    main()
