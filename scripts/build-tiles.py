#!/usr/bin/env python3
"""상권나우 신규/소멸 점포 전량 PMTiles 빌드 스크립트.

`scripts/build-data.py` 와 같은 원천(소진공 상가(상권)정보 분기 스냅샷 zip)을 같은
규칙(상가업소번호 diff, 최신 분기 기준 RegionRemapper 로 시군구/행정동 코드 보정)으로
다시 읽어서, `public/data/changes/*.json` 표본(시군구당 ~1,000+1,000) 대신
**신규/소멸 점포 전량**을 NDJSON GeoJSON Feature 스트림으로 스크래치에 쓴다.
그 다음 tippecanoe 로 `public/tiles/changes.pmtiles` 를 만든다.

opened/closed 여부는 기존과 같이 첫 분기(QUARTERS[0])↔마지막 분기(QUARTERS[-1]) 비교로
정해진다. 이번 확장은 그 사이 3개 분기 스냅샷을 추가로 읽어 "언제" 생기고 사라졌는지
분기 단위 근사치(속성 `q`, 1~4)를 덧붙인다:

  - opened(마지막 분기에 있고 첫 분기에 없음): QUARTERS[1:] 중 **처음 등장한 분기**의
    순번(1-based). 중간에 잠깐 없어졌다 다시 나온 경우도 "처음 등장" 기준.
  - closed(첫 분기에 있고 마지막 분기에 없음): QUARTERS[:-1] 중 **마지막으로 보인 분기**의
    순번(1-based, QUARTERS[0]=1).

표준 라이브러리만 사용(대용량 스트리밍: zipfile + csv, 메모리에 전체를 올리지 않음).
레코드 자체(좌표/속성)는 첫 분기(closed)/마지막 분기(opened)에서만 읽고 그 자리에서 바로
파일로 흘려보낸다. 중간 3개 분기는 store_id 집합만 메모리에 유지한다(각 ~270만개,
5개 집합 모두 올려도 감당 가능한 수준). 2-pass 구조:

  1) 모든 분기의 store_id 집합을 먼저 만든다(각 분기 1회 스트리밍, 레코드는 버림).
  2) 첫 분기를 다시 스트리밍하며, id 가 마지막 분기 집합에 없으면(=소멸) 그 자리에서
     바로 GeoJSON Feature 로 쓴다(q 는 1)의 나머지 분기 집합들로 즉시 계산).
  3) 마지막 분기를 다시 스트리밍하며, id 가 첫 분기 집합에 없으면(=신규) 마찬가지로 쓴다.

사용법:
    python3 scripts/build-tiles.py \
        --zip 202506=<zip> --zip 202509=<zip> --zip 202512=<zip> \
        --zip 202603=<zip> --zip 202606=<zip> \
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

# 5개 분기 스냅샷 순서(오래된 -> 최신). opened/closed 의 기준 분기(첫/마지막)와
# q 속성의 분기 순번은 모두 이 리스트 순서를 기준으로 한다.
QUARTERS = ["202506", "202509", "202512", "202603", "202606"]

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


def make_feature(row: list[str], k: int, sigungu_code: str, q: int) -> str:
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
        "q": q,
    }
    import json

    feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": props,
    }
    return json.dumps(feature, ensure_ascii=False)


def parse_zip_arg(raw: str) -> tuple[str, Path]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError(f"--zip 은 <분기>=<zip경로> 형식이어야 함: {raw!r}")
    quarter, _, path_str = raw.partition("=")
    if quarter not in QUARTERS:
        raise argparse.ArgumentTypeError(
            f"--zip 분기는 QUARTERS 중 하나여야 함({QUARTERS}): {quarter!r}"
        )
    return quarter, Path(path_str)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--zip", dest="zips", action="append", required=True, type=parse_zip_arg,
        metavar="분기=경로",
        help="예: --zip 202506=<zip경로> (QUARTERS 5개 전부 필요)",
    )
    ap.add_argument("--ndjson", required=True, type=Path)
    ap.add_argument(
        "--region-map", type=Path,
        default=Path(__file__).resolve().parent / "region-code-map.json",
    )
    args = ap.parse_args()

    zip_by_quarter: dict[str, Path] = dict(args.zips)
    missing = [q for q in QUARTERS if q not in zip_by_quarter]
    if missing:
        raise SystemExit(f"[build-tiles] --zip 누락: {missing} (QUARTERS={QUARTERS})")

    first_quarter, last_quarter = QUARTERS[0], QUARTERS[-1]
    first_zip, last_zip = zip_by_quarter[first_quarter], zip_by_quarter[last_quarter]
    # opened q 판정에 쓰는 후보 분기(오래된 -> 최신, 첫 분기 제외)
    opened_q_quarters = QUARTERS[1:]
    # closed q 판정에 쓰는 후보 분기(오래된 -> 최신, 마지막 분기 제외)
    closed_q_quarters = QUARTERS[:-1]

    print(f"[build-tiles] 최신 분기({last_quarter}) id 집합 수집: {last_zip}")
    last_ids = collect_ids(last_zip)
    print(f"  -> {len(last_ids):,} ids")

    print(f"[build-tiles] 최신 분기({last_quarter}) 행정동 인덱스 수집(remap 용): {last_zip}")
    cur_dong_meta = collect_dong_meta(last_zip)
    cur_dong_by_sigungu = build_cur_dong_index(cur_dong_meta)
    region_map = load_region_map(args.region_map)
    remapper = RegionRemapper(region_map, cur_dong_by_sigungu)

    print(f"[build-tiles] 첫 분기({first_quarter}) id 집합 수집: {first_zip}")
    first_ids = collect_ids(first_zip)
    print(f"  -> {len(first_ids):,} ids")

    # 중간 3개 분기의 id 집합(q 판정용). {분기: set[str]}
    mid_ids: dict[str, set[str]] = {}
    for quarter in QUARTERS[1:-1]:
        zpath = zip_by_quarter[quarter]
        print(f"[build-tiles] 중간 분기({quarter}) id 집합 수집: {zpath}")
        mid_ids[quarter] = collect_ids(zpath)
        print(f"  -> {len(mid_ids[quarter]):,} ids")

    def ids_of(quarter: str) -> set[str]:
        if quarter == first_quarter:
            return first_ids
        if quarter == last_quarter:
            return last_ids
        return mid_ids[quarter]

    def opened_q(store_id: str) -> int:
        """오래된 -> 최신 순으로 처음 등장한 분기의 1-based 순번."""
        for i, quarter in enumerate(opened_q_quarters, start=1):
            if store_id in ids_of(quarter):
                return i
        return len(opened_q_quarters)  # 마지막 분기에만 있음(안전망)

    def closed_q(store_id: str) -> int:
        """오래된 -> 최신 순으로 마지막으로 보인 분기의 1-based 순번."""
        last_seen = 1
        for i, quarter in enumerate(closed_q_quarters, start=1):
            if store_id in ids_of(quarter):
                last_seen = i
        return last_seen

    args.ndjson.parent.mkdir(parents=True, exist_ok=True)

    opened_written = closed_written = 0
    opened_dropped = closed_dropped = 0
    opened_q_hist = {1: 0, 2: 0, 3: 0, 4: 0}
    closed_q_hist = {1: 0, 2: 0, 3: 0, 4: 0}

    with args.ndjson.open("w", encoding="utf-8") as out:
        print(f"[build-tiles] 첫 분기({first_quarter}) 스트리밍 -> 소멸(closed, k=0) 판정")
        for row in iter_rows(first_zip):
            store_id = row[ID]
            if store_id in last_ids:
                continue  # 공통 id: 소멸 아님
            sigungu_code = row[SIGUNGU_CODE]
            dong_name = row[DONG_NAME]
            if remapper.is_affected(sigungu_code):
                sigungu_code = remapper.resolve_sigungu(sigungu_code, dong_name)
            q = closed_q(store_id)
            feature_line = make_feature(row, 0, sigungu_code, q)
            if feature_line is None:
                closed_dropped += 1
                continue
            out.write(feature_line)
            out.write("\n")
            closed_written += 1
            closed_q_hist[q] += 1

        print(f"[build-tiles] 최신 분기({last_quarter}) 스트리밍 -> 신규(opened, k=1) 판정")
        for row in iter_rows(last_zip):
            store_id = row[ID]
            if store_id in first_ids:
                continue  # 공통 id: 신규 아님
            sigungu_code = row[SIGUNGU_CODE]
            q = opened_q(store_id)
            feature_line = make_feature(row, 1, sigungu_code, q)
            if feature_line is None:
                opened_dropped += 1
                continue
            out.write(feature_line)
            out.write("\n")
            opened_written += 1
            opened_q_hist[q] += 1

    print("\n=== 요약 ===")
    print(f"opened: written={opened_written:,} dropped(좌표 결측/이상치)={opened_dropped:,}")
    print(f"  q 분포(1={opened_q_quarters[0]} .. 4={opened_q_quarters[-1]}): {opened_q_hist}")
    print(f"closed: written={closed_written:,} dropped(좌표 결측/이상치)={closed_dropped:,}")
    print(f"  q 분포(1={closed_q_quarters[0]} .. 4={closed_q_quarters[-1]}): {closed_q_hist}")
    print(f"총 피처 수: {opened_written + closed_written:,}")
    print(f"NDJSON: {args.ndjson}")


if __name__ == "__main__":
    main()
