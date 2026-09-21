#!/usr/bin/env python3
"""상권나우 신규/소멸 점포 전량 PMTiles 빌드 스크립트.

`scripts/build-data.py` 와 같은 원천(소진공 상가(상권)정보 분기 스냅샷 zip)을 같은
규칙(상가업소번호 diff, 최신 분기 기준 RegionRemapper 로 시군구/행정동 코드 보정)으로
다시 읽어서, `public/data/changes/*.json` 표본(시군구당 ~1,000+1,000) 대신
**신규/소멸 점포 전량**을 NDJSON GeoJSON Feature 스트림으로 스크래치에 쓴다.
그 다음 tippecanoe 로 `public/tiles/changes.pmtiles` 를 만든다.

opened/closed 여부는 기존과 같이 첫 분기(QUARTERS[0])↔마지막 분기(QUARTERS[-1]) 비교로
정해진다 — 단 상가업소번호 diff 만으로는 원본이 점포 번호를 재부여한 경우("같은 가게,
번호만 바뀜")가 소멸+신규로 이중 계산된다(2026-09-21 검증: 202603->202606 구간에서만
신규 34만/소멸 30만으로 다른 구간의 2~4배였음). 그래서 번호가 안 맞는 것들끼리
(정규화 상호명, 도로명주소, 층, 호) 키로 다시 매칭해(scripts/match.py) 짝이 맞는 쌍은
신규·소멸 양쪽에서 제외한다(build-data.py/build-insights.py 와 같은 규칙). 여기서도 짝을
못 찾은 것들끼리는 다시 (도로명주소, 층, 호, 상권업종소분류코드) 3차 매칭으로 "간판 바뀜
추정(renamed)"을 잡아낸다 — 이 쌍은 opened/closed 에서 빠지고, 신규 쪽 점 하나만
`k=2`(renamed)로 찍히며 속성에 이전 상호(`p`)가 붙는다(scripts/match.py 참고).

이번 확장은 그 사이 3개 분기 스냅샷을 추가로 읽어 "언제" 생기고 사라졌는지 분기 단위
근사치(속성 `q`, 1~4)를 덧붙인다. 각 분기에 "있었는가"는 번호 또는 (정규화 상호명,
도로명주소, 층, 호) 키 둘 중 하나라도 그 분기에 있으면 "있었다"로 본다 — 재부여 이후
번호만 바뀐 구간도 같은 가게로 이어 붙이기 위함:

  - opened(마지막 분기에 있고 첫 분기에 없음, 재부여 쌍 제외): QUARTERS[1:] 중
    **처음 등장한 분기**의 순번(1-based). 중간에 잠깐 없어졌다 다시 나온 경우도
    "처음 등장" 기준.
  - closed(첫 분기에 있고 마지막 분기에 없음, 재부여 쌍 제외): QUARTERS[:-1] 중
    **마지막으로 보인 분기**의 순번(1-based, QUARTERS[0]=1).

표준 라이브러리만 사용(대용량 스트리밍: zipfile + csv, 메모리에 전체를 올리지 않음).
레코드 자체(좌표/속성)는 첫 분기(closed)/마지막 분기(opened)에서만 읽고 그 자리에서 바로
파일로 흘려보낸다. 중간 3개 분기는 store_id 집합 + 매칭 키 집합만 메모리에 유지한다
(각 ~270만개, 5개 분기 모두 올려도 감당 가능한 수준). 첫/마지막 분기는 번호 재부여
매칭에 id->키 매핑이 필요해 그것까지 유지한다. 2-pass 구조:

  1) 모든 분기의 store_id 집합(+키 집합)을 먼저 만든다(각 분기 1회 스트리밍, 레코드는 버림).
  2) 첫 분기를 다시 스트리밍하며, id 가 마지막 분기 집합에 없고 재부여 매칭도 안 되면
     (=소멸) 그 자리에서 바로 GeoJSON Feature 로 쓴다(q 는 나머지 분기 집합들로 즉시 계산).
  3) 마지막 분기를 다시 스트리밍하며, id 가 첫 분기 집합에 없고 재부여 매칭도 안 되면
     (=신규) 마찬가지로 쓴다.

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
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from region_remap import RegionRemapper, build_cur_dong_index, load_region_map  # noqa: E402
from match import find_renamed_pairs, match_key, pair_ids_by_key  # noqa: E402
from license import (  # noqa: E402
    DEFAULT_LICENSE_MAP_PATH, classify_closed, classify_opened, load_license_map,
)

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
SMALL_CODE = IDX["상권업종소분류코드"]
SIGUNGU_CODE = IDX["시군구코드"]
DONG_NAME = IDX["행정동명"]
DONG_CODE = IDX["행정동코드"]
JIBUN_ADDR = IDX["지번주소"]
ROAD_ADDR = IDX["도로명주소"]
FLOOR = IDX["층정보"]
HO = IDX["호정보"]
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


def collect_ids_and_keys(zip_path: Path) -> tuple[set[str], dict[str, tuple], dict[str, tuple], Counter]:
    """id 집합, id -> match_key(정규화 상호명, 도로명주소, 층, 호) 매핑, id -> 3차("간판
    바뀜 추정") 원시 필드(도로명주소, 층, 호, 상권업종소분류코드) 매핑, 도로명주소 ->
    그 분기 전체 점포 수(4차 "단독 입주 건물" 보정용, 층/호 유무와 무관)를 한 번에 모은다.

    2차 키가 None(주소 없음/상호명 노이즈)인 행은 keys 매핑에서 빠진다 — 번호 재부여
    매칭 후보가 될 수 없다는 뜻(과매칭 방지, scripts/match.py 참고). 3차 원시 필드는
    (모든 행에 대해) 그대로 담아두고, 실제 키 계산(rename_key)과 None 필터링은
    find_renamed_pairs 호출 시점에 한다.
    첫/마지막 분기(경계 매칭에 id->key 매핑이 필요한 쪽)에만 쓴다.
    """
    ids: set[str] = set()
    keys: dict[str, tuple] = {}
    rename_fields: dict[str, tuple] = {}
    addr_counts: Counter = Counter()
    for row in iter_rows(zip_path):
        sid = row[ID]
        ids.add(sid)
        k = match_key(row[NAME], row[ROAD_ADDR], row[FLOOR], row[HO])
        if k is not None:
            keys[sid] = k
        rename_fields[sid] = (iv(row[ROAD_ADDR]), iv(row[FLOOR]), iv(row[HO]), iv(row[SMALL_CODE]))
        if row[ROAD_ADDR]:
            addr_counts[row[ROAD_ADDR]] += 1
    return ids, keys, rename_fields, addr_counts


def collect_ids_and_key_set(zip_path: Path) -> tuple[set[str], set[tuple]]:
    """중간 분기용: id 집합과 (id 연결 없이) 이번 분기에 존재하는 키의 집합만 모은다.

    분기 q(언제 생기고 사라졌는지) 판정에서 "이 분기에 이 가게가 있었는가"를
    번호 또는 키 둘 중 하나로 확인하면 되므로, 중간 분기는 id->key 매핑 대신
    더 가벼운 키 집합만 있으면 충분하다.
    """
    ids: set[str] = set()
    keys: set[tuple] = set()
    for row in iter_rows(zip_path):
        ids.add(row[ID])
        k = match_key(row[NAME], row[ROAD_ADDR], row[FLOOR], row[HO])
        if k is not None:
            keys.add(k)
    return ids, keys


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


def make_feature(
    row: list[str], k: int, sigungu_code: str, q: int, prev_name: str | None = None,
    a: int | None = None, c: int | None = None,
) -> str:
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
    if prev_name:
        props["p"] = prev_name
    if a is not None:
        props["a"] = str(a)  # lib/map-tiles.ts TileProps.a 는 string(YYYYMMDD, ymd() 가 .length/.slice 사용)
    if c is not None:
        props["c"] = str(c)
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
    ap.add_argument(
        "--license-map", type=Path, default=DEFAULT_LICENSE_MAP_PATH,
        help="scripts/build-license.py 가 만든 store_license_map.ndjson 경로 "
             "(없으면 이 보정 없이 기존 로직대로 동작)",
    )
    args = ap.parse_args()

    print(f"[build-tiles] 인허가 매핑 로드: {args.license_map}")
    license_map = load_license_map(args.license_map)
    print(f"  -> {len(license_map):,}건 (없으면 stale/unverified 보정 생략)")

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

    print(f"[build-tiles] 최신 분기({last_quarter}) id/키 집합 수집: {last_zip}")
    last_ids, last_keys, last_rename_fields, last_addr_counts = collect_ids_and_keys(last_zip)
    print(f"  -> {len(last_ids):,} ids, {len(last_keys):,} 매칭 가능 키")

    print(f"[build-tiles] 최신 분기({last_quarter}) 행정동 인덱스 수집(remap 용): {last_zip}")
    cur_dong_meta = collect_dong_meta(last_zip)
    cur_dong_by_sigungu = build_cur_dong_index(cur_dong_meta)
    region_map = load_region_map(args.region_map)
    remapper = RegionRemapper(region_map, cur_dong_by_sigungu)

    print(f"[build-tiles] 첫 분기({first_quarter}) id/키 집합 수집: {first_zip}")
    first_ids, first_keys, first_rename_fields, first_addr_counts = collect_ids_and_keys(first_zip)
    print(f"  -> {len(first_ids):,} ids, {len(first_keys):,} 매칭 가능 키")

    # 중간 3개 분기의 id 집합 + 키 집합(q 판정용, id 연결은 필요 없음). {분기: (set[str], set[tuple])}
    mid_ids: dict[str, set[str]] = {}
    mid_keys: dict[str, set[tuple]] = {}
    for quarter in QUARTERS[1:-1]:
        zpath = zip_by_quarter[quarter]
        print(f"[build-tiles] 중간 분기({quarter}) id/키 집합 수집: {zpath}")
        mid_ids[quarter], mid_keys[quarter] = collect_ids_and_key_set(zpath)
        print(f"  -> {len(mid_ids[quarter]):,} ids, {len(mid_keys[quarter]):,} 키")

    def ids_of(quarter: str) -> set[str]:
        if quarter == first_quarter:
            return first_ids
        if quarter == last_quarter:
            return last_ids
        return mid_ids[quarter]

    def keys_of(quarter: str) -> set[tuple]:
        if quarter == first_quarter:
            return set(first_keys.values())
        if quarter == last_quarter:
            return set(last_keys.values())
        return mid_keys[quarter]

    # ------------------------------------------------------------------
    # 번호 재부여 매칭: 첫 분기에만 있는 id(raw_closed) / 마지막 분기에만
    # 있는 id(raw_opened) 중, (정규화 상호명, 도로명주소, 층, 호) 키로 짝이
    # 맞는 쌍은 "같은 가게, 번호만 바뀜"으로 보고 신규·소멸 양쪽에서 제외한다
    # (scripts/match.py 참고). build-data.py/build-insights.py 와 동일한
    # 첫/마지막 분기(202506/202606) 조합이라 같은 결과가 나온다.
    # ------------------------------------------------------------------
    raw_closed_ids = first_ids - last_ids
    raw_opened_ids = last_ids - first_ids
    prev_key_of = {sid: k for sid, k in first_keys.items() if sid in raw_closed_ids}
    cur_key_of = {sid: k for sid, k in last_keys.items() if sid in raw_opened_ids}
    matched_prev, matched_cur, renumbered_pairs, ambiguous_groups = pair_ids_by_key(prev_key_of, cur_key_of)
    print(
        f"[build-tiles] 번호 재부여로 제외된 쌍: {len(renumbered_pairs):,} "
        f"(모호한 키 그룹 {ambiguous_groups:,}건)"
    )
    tier2_closed_ids = raw_closed_ids - matched_prev
    tier2_opened_ids = raw_opened_ids - matched_cur
    print(f"  -> 2차까지 opened={len(tier2_opened_ids):,} closed={len(tier2_closed_ids):,}")

    # ------------------------------------------------------------------
    # 간판 바뀜 추정 매칭(3차): 1·2차에서도 짝을 못 찾은 소멸/신규 중
    # (도로명주소, 층, 호, 상권업종소분류코드)가 같고 1:1인 쌍만 "같은 자리,
    # 간판만 바뀐 것으로 추정"하여 opened/closed 에서 빼고 renamed 로 센다
    # (scripts/match.py 참고). build-data.py/build-insights.py 와 동일한
    # 첫/마지막 분기(202506/202606) 조합이라 같은 결과가 나온다.
    # ------------------------------------------------------------------
    rename_prev_only = {sid: first_rename_fields[sid] for sid in tier2_closed_ids}
    rename_cur_only = {sid: last_rename_fields[sid] for sid in tier2_opened_ids}
    (
        renamed_prev_ids, renamed_cur_ids, renamed_pairs,
        renamed_excluded_both_empty, renamed_ambiguous_groups, renamed_tier4_pairs,
    ) = find_renamed_pairs(rename_prev_only, rename_cur_only, first_addr_counts, last_addr_counts)
    prev_id_of_renamed_cur = {cur_id: prev_id for prev_id, cur_id in renamed_pairs}
    print(
        f"[build-tiles] 간판 바뀜 추정 쌍: {len(renamed_pairs):,} "
        f"(그중 4차 단독 입주 보정 {len(renamed_tier4_pairs):,}건) "
        f"(층/호 둘다 빈값+단독입주 아님이라 제외 {renamed_excluded_both_empty:,}건, "
        f"모호한 키 그룹 {renamed_ambiguous_groups:,}건)"
    )

    final_closed_ids = tier2_closed_ids - renamed_prev_ids
    final_opened_ids = tier2_opened_ids - renamed_cur_ids
    print(
        f"  -> 최종 opened={len(final_opened_ids):,} closed={len(final_closed_ids):,} "
        f"renamed={len(renamed_pairs):,}"
    )

    def opened_q(store_id: str, own_key: tuple | None) -> int:
        """오래된 -> 최신 순으로 "처음 등장한" 분기의 1-based 순번.

        등장 여부는 번호 또는 (정규화 상호명, 도로명주소, 층, 호) 키 둘 중
        하나라도 그 분기에 있으면 "있었다"로 본다 — 재부여 이후 번호만 바뀐
        연속 구간을 같은 가게로 이어 붙이기 위함.
        """
        for i, quarter in enumerate(opened_q_quarters, start=1):
            if store_id in ids_of(quarter) or (own_key is not None and own_key in keys_of(quarter)):
                return i
        return len(opened_q_quarters)  # 마지막 분기에만 있음(안전망)

    def closed_q(store_id: str, own_key: tuple | None) -> int:
        """오래된 -> 최신 순으로 "마지막으로 보인" 분기의 1-based 순번(번호 또는 키 기준)."""
        last_seen = 1
        for i, quarter in enumerate(closed_q_quarters, start=1):
            if store_id in ids_of(quarter) or (own_key is not None and own_key in keys_of(quarter)):
                last_seen = i
        return last_seen

    args.ndjson.parent.mkdir(parents=True, exist_ok=True)

    opened_written = closed_written = renamed_written = 0
    stale_written = unverified_written = 0
    opened_dropped = closed_dropped = renamed_dropped = 0
    opened_excluded_renumbered = closed_excluded_renumbered = 0
    opened_q_hist = {1: 0, 2: 0, 3: 0, 4: 0}
    closed_q_hist = {1: 0, 2: 0, 3: 0, 4: 0}
    renamed_q_hist = {1: 0, 2: 0, 3: 0, 4: 0}
    stale_q_hist = {1: 0, 2: 0, 3: 0, 4: 0}
    unverified_q_hist = {1: 0, 2: 0, 3: 0, 4: 0}
    # 3차(간판 바뀜 추정) 소멸 쪽에서 원래 상호명을 잡아뒀다가, 신규 쪽 피처의
    # "p"(이전 상호) 속성에 쓴다(첫 분기 스트리밍 중에 채움).
    rename_name_of: dict[str, str] = {}

    with args.ndjson.open("w", encoding="utf-8") as out:
        print(f"[build-tiles] 첫 분기({first_quarter}) 스트리밍 -> 소멸(closed, k=0) 판정")
        for row in iter_rows(first_zip):
            store_id = row[ID]
            if store_id in last_ids:
                continue  # 공통 id: 소멸 아님
            if store_id in matched_prev:
                closed_excluded_renumbered += 1
                continue  # 번호만 재부여됨: 소멸 아님
            if store_id in renamed_prev_ids:
                rename_name_of[store_id] = row[NAME]
                continue  # 간판 바뀜 추정: 소멸 아님(renamed 로 별도 집계, 신규 쪽에서만 점을 찍음)
            sigungu_code = row[SIGUNGU_CODE]
            dong_name = row[DONG_NAME]
            if remapper.is_affected(sigungu_code):
                sigungu_code = remapper.resolve_sigungu(sigungu_code, dong_name)
            own_key = match_key(row[NAME], row[ROAD_ADDR], row[FLOOR], row[HO])
            q = closed_q(store_id, own_key)
            reclass = classify_closed(store_id, license_map)
            if reclass.new_k == 4:
                # unverified: 인허가상 아직 영업 중 — closed 목록에서 빼고 별도 k=4 로 찍는다.
                feature_line = make_feature(row, 4, sigungu_code, q, a=reclass.a, c=reclass.c)
                if feature_line is None:
                    closed_dropped += 1
                    continue
                out.write(feature_line)
                out.write("\n")
                unverified_written += 1
                unverified_q_hist[q] += 1
                continue
            q_final = reclass.q_override if reclass.q_override is not None else q
            feature_line = make_feature(row, 0, sigungu_code, q_final, a=reclass.a, c=reclass.c)
            if feature_line is None:
                closed_dropped += 1
                continue
            out.write(feature_line)
            out.write("\n")
            closed_written += 1
            closed_q_hist[q_final] += 1

        print(f"[build-tiles] 최신 분기({last_quarter}) 스트리밍 -> 신규(opened, k=1)/간판바뀜(renamed, k=2) 판정")
        for row in iter_rows(last_zip):
            store_id = row[ID]
            if store_id in first_ids:
                continue  # 공통 id: 신규 아님
            if store_id in matched_cur:
                opened_excluded_renumbered += 1
                continue  # 번호만 재부여됨: 신규 아님
            sigungu_code = row[SIGUNGU_CODE]
            own_key = match_key(row[NAME], row[ROAD_ADDR], row[FLOOR], row[HO])
            q = opened_q(store_id, own_key)
            if store_id in renamed_cur_ids:
                prev_id = prev_id_of_renamed_cur.get(store_id)
                prev_name = rename_name_of.get(prev_id, "") if prev_id else ""
                feature_line = make_feature(row, 2, sigungu_code, q, prev_name=prev_name)
                if feature_line is None:
                    renamed_dropped += 1
                    continue
                out.write(feature_line)
                out.write("\n")
                renamed_written += 1
                renamed_q_hist[q] += 1
                continue
            reclass = classify_opened(store_id, license_map)
            if reclass.new_k == 3:
                # stale: 인허가상 이미 예전부터 영업 중(등록 지연) — opened 목록에서 빼고 k=3.
                feature_line = make_feature(row, 3, sigungu_code, q, a=reclass.a, c=reclass.c)
                if feature_line is None:
                    opened_dropped += 1
                    continue
                out.write(feature_line)
                out.write("\n")
                stale_written += 1
                stale_q_hist[q] += 1
                continue
            q_final = reclass.q_override if reclass.q_override is not None else q
            feature_line = make_feature(row, 1, sigungu_code, q_final, a=reclass.a, c=reclass.c)
            if feature_line is None:
                opened_dropped += 1
                continue
            out.write(feature_line)
            out.write("\n")
            opened_written += 1
            opened_q_hist[q_final] += 1

    print("\n=== 요약 ===")
    print(f"opened: written={opened_written:,} dropped(좌표 결측/이상치)={opened_dropped:,} "
          f"제외(번호재부여)={opened_excluded_renumbered:,} 제외(stale)={stale_written:,}")
    print(f"  q 분포(1={opened_q_quarters[0]} .. 4={opened_q_quarters[-1]}, 허가일 있으면 허가일분기로 덮어씀): {opened_q_hist}")
    print(f"stale(k=3, 예전부터 영업/등록지연): written={stale_written:,} q분포(허가일분기): {stale_q_hist}")
    print(f"unverified(k=4, 소멸인데 인허가상 영업중): written={unverified_written:,} q분포(마지막목격분기): {unverified_q_hist}")
    print(f"closed: written={closed_written:,} dropped(좌표 결측/이상치)={closed_dropped:,} "
          f"제외(번호재부여)={closed_excluded_renumbered:,} 제외(unverified)={unverified_written:,}")
    print(f"  q 분포(1={closed_q_quarters[0]} .. 4={closed_q_quarters[-1]}, 폐업일 있으면 폐업일분기로 덮어씀): {closed_q_hist}")
    print(f"renamed(k=2, 신규 쪽만 기록): written={renamed_written:,} dropped(좌표 결측/이상치)={renamed_dropped:,}")
    print(f"  q 분포(1={opened_q_quarters[0]} .. 4={opened_q_quarters[-1]}): {renamed_q_hist}")
    print(f"총 피처 수: {opened_written + closed_written + renamed_written + stale_written + unverified_written:,}")
    print(f"NDJSON: {args.ndjson}")


if __name__ == "__main__":
    main()
