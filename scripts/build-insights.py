#!/usr/bin/env python3
"""상권나우 "인사이트" 파생 데이터 빌드 스크립트.

`scripts/build-data.py` 가 만드는 "숫자 나열"(시군구/동/업종 카운트) 위에,
사람이 읽을 만한 인사이트를 얹기 위한 산출물을 만든다:

1. 업종 통계 (중분류 전체 75개 + 소분류 전체) — 전국/시군구별
2. 업종 전환 — 사라진 가게 자리에 어떤 업종이 새로 생겼는가 (주소 매칭)
3. 브랜드 — 상호명 정규화 기반 프랜차이즈 추정 집계
4. 연도별 추이 — 2022~2026 5개 시점(6월 분기) 업종별 전국 점포 수

원본에는 "폐업"이 없다(영업 중인 곳만 수록). 두 분기 스냅샷을 상가업소번호로
비교해 opened/closed 를 "추정"하는 것은 build-data.py 와 동일한 전제다.
이 스크립트가 추가로 만드는 파생값(전환/브랜드/연도추이)은 전부 근사치이며,
아래 각 섹션에 가정과 한계를 주석으로 남긴다.

표준 라이브러리만 사용, pandas 없이 스트리밍으로 CSV를 읽는다(zipfile + csv).
두 메인 분기(현재/이전)의 상가업소번호 -> 레코드는 메모리에 올린다(277만 x 2).

사용법:
    python3 scripts/build-insights.py \
        --current-zip <202606 zip> --current-quarter 202606 \
        --previous-zip <202506 zip> --previous-quarter 202506 \
        --year 2022=<hist_20220630.zip> \
        --year 2023=<hist_20230630.zip> \
        --year 2024=<hist_20240630.zip> \
        --sigungu-json data/sigungu.json \
        --out data/insights/
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from collections import Counter, defaultdict, namedtuple
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from region_remap import RegionRemapper, build_cur_dong_index, load_region_map  # noqa: E402
from normalize import BRAND_NOISE, brand_is_noise, normalize_brand  # noqa: E402
from match import find_renamed_pairs, resolve_opened_closed  # noqa: E402

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

# 39컬럼 스펙(build-data.py 와 동일, 2022~2026 5개 시점 모두 이 순서로 확인됨).
# 그래도 컬럼 순서가 다를 가능성에 대비해 헤더 이름으로 인덱스를 찾는다(HEADER 기반).
EXPECTED_FIRST_COLUMN = "상가업소번호"

REQUIRED_COLUMNS = [
    "상가업소번호", "상호명", "지점명",
    "상권업종대분류코드", "상권업종대분류명",
    "상권업종중분류코드", "상권업종중분류명",
    "상권업종소분류코드", "상권업종소분류명",
    "시도명", "시군구코드", "시군구명",
    "행정동명", "도로명주소", "층정보", "호정보",
    "경도", "위도",
]

KR_LAT_RANGE = (32.5, 39.5)
KR_LON_RANGE = (124.0, 132.5)

BRAND_MIN_STORES = 50
BRAND_NATIONAL_TOP_N = 300
BRAND_REGION_TOP_N = 30

TRANSITION_NATIONAL_TOP_N = 100
TRANSITION_REGION_TOP_N = 20
TRANSITION_EXAMPLES_PER_REGION = 30

SMALL_REGION_TOP_N = 40

MAX_REGION_FILE_BYTES = 60_000

Record = namedtuple(
    "Record",
    [
        "sigungu_code", "sigungu_name", "sido_name", "dong_name",
        "mid_code", "mid_name", "small_code", "small_name",
        "large_code", "large_name",
        "name", "branch", "road", "floor", "ho", "lon", "lat",
    ],
)


def iv(s: str):
    return sys.intern(s) if s else s


# 브랜드 정규화(normalize_brand/brand_is_noise/BRAND_NOISE)는 scripts/normalize.py 로
# 옮겨 scripts/match.py 와 공유한다(위 import 참고).

# ---------------------------------------------------------------------------
# CSV 스트리밍 파서
# ---------------------------------------------------------------------------

def _open_zip_csv_members(z: zipfile.ZipFile):
    """zip 안의 실제 데이터 csv 멤버만 골라 (member, header_indexes) 를 yield.

    - "필독"/안내 파일처럼 작은 파일은 헤더 검증에서 걸러진다.
    - 헤더는 파일마다 새로 읽어 컬럼 인덱스를 다시 계산한다(순서가 달라도
      안전하도록 — 실제로는 2022~2026 모두 동일한 순서였음을 확인했다).
    """
    for member in sorted(n for n in z.namelist() if n.lower().endswith(".csv")):
        info = z.getinfo(member)
        if info.file_size < 10_000:
            # "필독"/안내용 csv (수백~수천 바이트) — 실데이터 아님
            continue
        with z.open(member) as raw:
            tf = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            reader = csv.reader(tf)
            try:
                header = next(reader)
            except StopIteration:
                continue
        header_clean = [h.strip().strip('"') for h in header]
        if not header_clean or header_clean[0] != EXPECTED_FIRST_COLUMN:
            print(f"  [경고] {member}: 헤더 첫 컬럼이 예상과 다름({header_clean[:1]}), 건너뜀", file=sys.stderr)
            continue
        missing = [c for c in REQUIRED_COLUMNS if c not in header_clean]
        if missing:
            print(f"  [경고] {member}: 필수 컬럼 누락 {missing}, 건너뜀", file=sys.stderr)
            continue
        idx = {name: i for i, name in enumerate(header_clean)}
        yield member, idx


def _iter_zip_rows(zip_path: Path):
    """zip(또는 zip 안에 zip 하나 더 있는 2022 케이스) 안의 모든 데이터 행을 스트리밍.

    yield: (row: list[str], idx: dict[str,int])
    """
    with zipfile.ZipFile(zip_path) as z:
        csv_names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            # 2022 분기: zip 안에 폴더 + zip 파일이 하나 더 있는 구조
            inner_names = [n for n in z.namelist() if n.lower().endswith(".zip")]
            if not inner_names:
                raise SystemExit(f"[build-insights] {zip_path} 안에 csv/zip 이 없습니다")
            print(f"  [{zip_path.name}] 중첩 zip 발견: {inner_names[0]}")
            data = z.read(inner_names[0])
            with zipfile.ZipFile(io.BytesIO(data)) as z2:
                yield from _iter_zip_rows_from_open(z2, zip_path.name)
            return
        yield from _iter_zip_rows_from_open(z, zip_path.name)


def _iter_zip_rows_from_open(z: zipfile.ZipFile, label: str):
    for member, idx in _open_zip_csv_members(z):
        with z.open(member) as raw:
            tf = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            reader = csv.reader(tf)
            next(reader)  # header
            n = 0
            for row in reader:
                if len(row) < len(idx):
                    continue
                n += 1
                yield row, idx
            print(f"  [{label}] {member}: {n:,} rows")


# ---------------------------------------------------------------------------
# 메인 두 분기(현재/이전) 파싱 — 전체 레코드를 메모리에 적재
# ---------------------------------------------------------------------------

class QuarterData:
    def __init__(self, label: str):
        self.label = label
        self.records: dict[str, Record] = {}
        self.row_count = 0
        self.bad_rows = 0


def parse_quarter_full(
    zip_path: Path,
    label: str,
    remapper: RegionRemapper | None = None,
    cur_sigungu_names: dict[str, tuple[str, str]] | None = None,
) -> QuarterData:
    """`remapper`/`cur_sigungu_names` 는 이전 분기(202506) 파싱에만 넘긴다.

    202606부터 전남/광주가 "전남광주통합특별시"로 통합되고(시군구 코드 27개 새로
    부여, 이름은 그대로), 인천 중구/동구/서구·경기 화성시가 각각 여러 구로 쪼개지며
    시군구명·코드가 바뀌었다. 이전 분기 원본 코드를 그대로 쓰면 이 지역들이
    "직전 분기엔 있었는데 이번엔 통째로 사라짐 + 이번 분기엔 있는데 직전엔 아예 없었음"
    으로 잘못 집계된다. 자세한 매핑 로직은 region_remap.py 참고.
    """
    qd = QuarterData(label)
    for row, idx in _iter_zip_rows(zip_path):
        try:
            store_id = row[idx["상가업소번호"]]
            lon_raw, lat_raw = row[idx["경도"]], row[idx["위도"]]
            lon = lat = None
            if lon_raw and lat_raw:
                try:
                    lon = round(float(lon_raw), 6)
                    lat = round(float(lat_raw), 6)
                except ValueError:
                    lon = lat = None

            sigungu_code = row[idx["시군구코드"]]
            sigungu_name = row[idx["시군구명"]]
            sido_name = row[idx["시도명"]]
            dong_name = row[idx["행정동명"]]
            if remapper is not None and remapper.is_affected(sigungu_code):
                sigungu_code = remapper.resolve_sigungu(sigungu_code, dong_name)
                if cur_sigungu_names and sigungu_code in cur_sigungu_names:
                    sido_name, sigungu_name = cur_sigungu_names[sigungu_code]

            rec = Record(
                sigungu_code=iv(sigungu_code),
                sigungu_name=iv(sigungu_name),
                sido_name=iv(sido_name),
                dong_name=iv(dong_name),
                mid_code=iv(row[idx["상권업종중분류코드"]]),
                mid_name=iv(row[idx["상권업종중분류명"]]),
                small_code=iv(row[idx["상권업종소분류코드"]]),
                small_name=iv(row[idx["상권업종소분류명"]]),
                large_code=iv(row[idx["상권업종대분류코드"]]),
                large_name=iv(row[idx["상권업종대분류명"]]),
                name=row[idx["상호명"]],
                branch=row[idx["지점명"]],
                road=row[idx["도로명주소"]],
                floor=row[idx["층정보"]],
                ho=row[idx["호정보"]],
                lon=lon, lat=lat,
            )
        except (IndexError, KeyError):
            qd.bad_rows += 1
            continue
        qd.records[store_id] = rec
        qd.row_count += 1
    return qd


def count_by_name_only(zip_path: Path, label: str) -> tuple[Counter, Counter]:
    """예전 연도 스냅샷용: 레코드 전체를 들고 있지 않고 중분류/소분류 이름만 센다."""
    mid_counter: Counter = Counter()
    small_counter: Counter = Counter()
    n = 0
    for row, idx in _iter_zip_rows(zip_path):
        try:
            mid_counter[row[idx["상권업종중분류명"]]] += 1
            small_counter[row[idx["상권업종소분류명"]]] += 1
        except (IndexError, KeyError):
            continue
        n += 1
    print(f"  [{label}] 총 {n:,} rows")
    return mid_counter, small_counter


# ---------------------------------------------------------------------------
# 1) 업종 통계 (중분류/소분류, 전국 + 시군구)
# ---------------------------------------------------------------------------

def build_upjong_stats(cur: QuarterData, prev: QuarterData, opened_ids, closed_ids):
    """반환: (national_middle, national_small, region_middle_by_code, region_small_by_code)"""

    cur_mid_counter: Counter = Counter()
    prev_mid_counter: Counter = Counter()
    cur_small_counter: Counter = Counter()
    prev_small_counter: Counter = Counter()
    mid_meta: dict[str, str] = {}
    small_meta: dict[str, tuple[str, str]] = {}  # small_code -> (small_name, mid_code)

    cur_sigungu_mid: Counter = Counter()
    prev_sigungu_mid: Counter = Counter()
    cur_sigungu_small: Counter = Counter()
    prev_sigungu_small: Counter = Counter()

    for r in cur.records.values():
        cur_mid_counter[r.mid_code] += 1
        cur_small_counter[r.small_code] += 1
        mid_meta.setdefault(r.mid_code, r.mid_name)
        small_meta.setdefault(r.small_code, (r.small_name, r.mid_code))
        cur_sigungu_mid[(r.sigungu_code, r.mid_code)] += 1
        cur_sigungu_small[(r.sigungu_code, r.small_code)] += 1

    for r in prev.records.values():
        prev_mid_counter[r.mid_code] += 1
        prev_small_counter[r.small_code] += 1
        mid_meta.setdefault(r.mid_code, r.mid_name)
        small_meta.setdefault(r.small_code, (r.small_name, r.mid_code))
        prev_sigungu_mid[(r.sigungu_code, r.mid_code)] += 1
        prev_sigungu_small[(r.sigungu_code, r.small_code)] += 1

    opened_mid: Counter = Counter()
    closed_mid: Counter = Counter()
    opened_small: Counter = Counter()
    closed_small: Counter = Counter()
    opened_sigungu_mid: Counter = Counter()
    closed_sigungu_mid: Counter = Counter()
    opened_sigungu_small: Counter = Counter()
    closed_sigungu_small: Counter = Counter()

    for sid in opened_ids:
        r = cur.records[sid]
        opened_mid[r.mid_code] += 1
        opened_small[r.small_code] += 1
        opened_sigungu_mid[(r.sigungu_code, r.mid_code)] += 1
        opened_sigungu_small[(r.sigungu_code, r.small_code)] += 1
    for sid in closed_ids:
        r = prev.records[sid]
        closed_mid[r.mid_code] += 1
        closed_small[r.small_code] += 1
        closed_sigungu_mid[(r.sigungu_code, r.mid_code)] += 1
        closed_sigungu_small[(r.sigungu_code, r.small_code)] += 1

    def _stat(code, stores, prev_stores, opened, closed, name, extra):
        prevs = prev_stores or 0
        return {
            "code": code, "name": name,
            "stores": stores, "prevStores": prevs,
            "opened": opened, "closed": closed,
            "closeRate": round(closed / prevs, 4) if prevs else 0.0,
            "openRate": round(opened / prevs, 4) if prevs else 0.0,
            **extra,
        }

    all_mid_codes = set(mid_meta)
    national_middle = [
        _stat(
            code, cur_mid_counter.get(code, 0), prev_mid_counter.get(code, 0),
            opened_mid.get(code, 0), closed_mid.get(code, 0), mid_meta[code],
            {},
        )
        for code in all_mid_codes
    ]
    national_middle.sort(key=lambda r: -r["stores"])

    all_small_codes = set(small_meta)
    national_small = [
        _stat(
            code, cur_small_counter.get(code, 0), prev_small_counter.get(code, 0),
            opened_small.get(code, 0), closed_small.get(code, 0), small_meta[code][0],
            {"middleCode": small_meta[code][1], "middleName": mid_meta.get(small_meta[code][1], "")},
        )
        for code in all_small_codes
    ]
    national_small.sort(key=lambda r: -r["stores"])

    # 시군구별
    region_middle: dict[str, list[dict]] = defaultdict(list)
    sigungu_codes_with_mid = {sc for (sc, _mc) in set(cur_sigungu_mid) | set(prev_sigungu_mid)}
    for sigungu_code in sigungu_codes_with_mid:
        for code in all_mid_codes:
            stores = cur_sigungu_mid.get((sigungu_code, code), 0)
            prev_stores = prev_sigungu_mid.get((sigungu_code, code), 0)
            if stores == 0 and prev_stores == 0:
                continue
            region_middle[sigungu_code].append(_stat(
                code, stores, prev_stores,
                opened_sigungu_mid.get((sigungu_code, code), 0),
                closed_sigungu_mid.get((sigungu_code, code), 0),
                mid_meta[code], {},
            ))
        region_middle[sigungu_code].sort(key=lambda r: -r["stores"])

    region_small: dict[str, list[dict]] = defaultdict(list)
    sigungu_codes_with_small = {sc for (sc, _c) in set(cur_sigungu_small) | set(prev_sigungu_small)}
    for sigungu_code in sigungu_codes_with_small:
        rows = []
        codes_seen = {c for (sc, c) in cur_sigungu_small if sc == sigungu_code} | \
                     {c for (sc, c) in prev_sigungu_small if sc == sigungu_code}
        for code in codes_seen:
            stores = cur_sigungu_small.get((sigungu_code, code), 0)
            prev_stores = prev_sigungu_small.get((sigungu_code, code), 0)
            name, mid_code = small_meta[code]
            rows.append(_stat(
                code, stores, prev_stores,
                opened_sigungu_small.get((sigungu_code, code), 0),
                closed_sigungu_small.get((sigungu_code, code), 0),
                name, {"middleCode": mid_code, "middleName": mid_meta.get(mid_code, "")},
            ))
        rows.sort(key=lambda r: -r["stores"])
        region_small[sigungu_code] = rows[:SMALL_REGION_TOP_N]

    return national_middle, national_small, region_middle, region_small


# ---------------------------------------------------------------------------
# 2) 업종 전환 (주소 매칭)
# ---------------------------------------------------------------------------

def build_transitions(cur: QuarterData, prev: QuarterData, opened_ids, closed_ids):
    closed_by_key: dict[tuple, list[str]] = defaultdict(list)
    opened_by_key: dict[tuple, list[str]] = defaultdict(list)

    for sid in closed_ids:
        r = prev.records[sid]
        if not r.road:
            continue  # 도로명주소 없는 곳은 자리 매칭 신뢰도가 없어 제외
        closed_by_key[(r.road, r.floor, r.ho)].append(sid)
    for sid in opened_ids:
        r = cur.records[sid]
        if not r.road:
            continue
        opened_by_key[(r.road, r.floor, r.ho)].append(sid)

    national_counter: Counter = Counter()  # (fromCode,fromName,toCode,toName) -> count
    region_counter: dict[str, Counter] = defaultdict(Counter)
    region_examples: dict[str, list[dict]] = defaultdict(list)
    matched_total = 0

    shared_keys = set(closed_by_key) & set(opened_by_key)
    for key in shared_keys:
        closed_list = closed_by_key[key]
        opened_list = opened_by_key[key]
        # 한 자리에 여러 건이면 1:1로만 잇고 나머지는 버린다(과대집계 방지).
        for closed_sid, opened_sid in zip(closed_list, opened_list):
            c = prev.records[closed_sid]
            o = cur.records[opened_sid]
            matched_total += 1
            tkey = (c.mid_code, c.mid_name, o.mid_code, o.mid_name)
            national_counter[tkey] += 1
            region_counter[o.sigungu_code][tkey] += 1

            if (
                c.name and o.name
                and c.name not in BRAND_NOISE and o.name not in BRAND_NOISE
                and len(region_examples[o.sigungu_code]) < TRANSITION_EXAMPLES_PER_REGION * 6
            ):
                region_examples[o.sigungu_code].append({
                    "road": o.road,
                    "dong": o.dong_name,
                    "fromName": c.name,
                    "fromUpjong": c.mid_name,
                    "toName": o.name,
                    "toUpjong": o.mid_name,
                    "lat": o.lat if o.lat is not None else 0.0,
                    "lon": o.lon if o.lon is not None else 0.0,
                })

    def _transition_rows(counter: Counter, top_n: int):
        rows = [
            {"fromCode": fc, "fromName": fn, "toCode": tc, "toName": tn, "count": cnt}
            for (fc, fn, tc, tn), cnt in counter.items()
        ]
        rows.sort(key=lambda r: -r["count"])
        return rows[:top_n]

    national_transitions = _transition_rows(national_counter, TRANSITION_NATIONAL_TOP_N)

    region_transitions = {
        code: _transition_rows(cnt, TRANSITION_REGION_TOP_N)
        for code, cnt in region_counter.items()
    }

    region_examples_final: dict[str, list[dict]] = {}
    for code, examples in region_examples.items():
        # 동네 골고루: 행정동별로 라운드로빈 선택
        by_dong: dict[str, list[dict]] = defaultdict(list)
        for ex in examples:
            by_dong[ex["dong"]].append(ex)
        dong_keys = list(by_dong.keys())
        picked = []
        i = 0
        while len(picked) < TRANSITION_EXAMPLES_PER_REGION and any(by_dong.values()):
            k = dong_keys[i % len(dong_keys)]
            if by_dong[k]:
                picked.append(by_dong[k].pop(0))
            i += 1
            if i > 10000:
                break
        region_examples_final[code] = picked[:TRANSITION_EXAMPLES_PER_REGION]

    return national_transitions, matched_total, region_transitions, region_examples_final


# ---------------------------------------------------------------------------
# 3) 브랜드
# ---------------------------------------------------------------------------

def build_brands(cur: QuarterData, prev: QuarterData, opened_ids, closed_ids):
    cur_brand_of: dict[str, str] = {}
    prev_brand_of: dict[str, str] = {}

    cur_brand_counter: Counter = Counter()
    for sid, r in cur.records.items():
        b = normalize_brand(r.name)
        cur_brand_of[sid] = b
        if b and not brand_is_noise(b):
            cur_brand_counter[b] += 1

    recognized = {b for b, c in cur_brand_counter.items() if c >= BRAND_MIN_STORES}
    print(f"  인식된 브랜드 수(전국 {BRAND_MIN_STORES}곳 이상): {len(recognized):,}")

    prev_brand_counter: Counter = Counter()
    for sid, r in prev.records.items():
        b = normalize_brand(r.name)
        prev_brand_of[sid] = b
        if b in recognized:
            prev_brand_counter[b] += 1

    opened_brand_counter: Counter = Counter()
    for sid in opened_ids:
        b = cur_brand_of.get(sid, "")
        if b in recognized:
            opened_brand_counter[b] += 1

    closed_brand_counter: Counter = Counter()
    for sid in closed_ids:
        b = prev_brand_of.get(sid, "")
        if b in recognized:
            closed_brand_counter[b] += 1

    brand_mid_counter: dict[str, Counter] = defaultdict(Counter)
    for sid, r in cur.records.items():
        b = cur_brand_of.get(sid, "")
        if b in recognized:
            brand_mid_counter[b][r.mid_name] += 1

    def _brand_row(b):
        mid_name = brand_mid_counter[b].most_common(1)[0][0] if brand_mid_counter[b] else ""
        return {
            "name": b,
            "upjong": mid_name,
            "stores": cur_brand_counter.get(b, 0),
            "prevStores": prev_brand_counter.get(b, 0),
            "opened": opened_brand_counter.get(b, 0),
            "closed": closed_brand_counter.get(b, 0),
        }

    national_brands = sorted(
        (_brand_row(b) for b in recognized),
        key=lambda r: -r["stores"],
    )[:BRAND_NATIONAL_TOP_N]

    # 시군구별
    region_cur: dict[tuple[str, str], int] = Counter()
    region_prev: dict[tuple[str, str], int] = Counter()
    region_opened: dict[tuple[str, str], int] = Counter()
    region_closed: dict[tuple[str, str], int] = Counter()

    for sid, r in cur.records.items():
        b = cur_brand_of.get(sid, "")
        if b in recognized:
            region_cur[(r.sigungu_code, b)] += 1
    for sid, r in prev.records.items():
        b = prev_brand_of.get(sid, "")
        if b in recognized:
            region_prev[(r.sigungu_code, b)] += 1
    for sid in opened_ids:
        r = cur.records[sid]
        b = cur_brand_of.get(sid, "")
        if b in recognized:
            region_opened[(r.sigungu_code, b)] += 1
    for sid in closed_ids:
        r = prev.records[sid]
        b = prev_brand_of.get(sid, "")
        if b in recognized:
            region_closed[(r.sigungu_code, b)] += 1

    region_brands: dict[str, list[dict]] = defaultdict(list)
    brands_by_region: dict[str, set[str]] = defaultdict(set)
    for (code, b) in region_cur:
        brands_by_region[code].add(b)
    for (code, b) in region_prev:
        brands_by_region[code].add(b)

    for code, brands in brands_by_region.items():
        rows = []
        for b in brands:
            rows.append({
                "name": b,
                "upjong": brand_mid_counter[b].most_common(1)[0][0] if brand_mid_counter[b] else "",
                "stores": region_cur.get((code, b), 0),
                "prevStores": region_prev.get((code, b), 0),
                "opened": region_opened.get((code, b), 0),
                "closed": region_closed.get((code, b), 0),
            })
        rows.sort(key=lambda r: -r["stores"])
        region_brands[code] = rows[:BRAND_REGION_TOP_N]

    return national_brands, region_brands, cur_brand_counter, recognized


# ---------------------------------------------------------------------------
# 4) 연도별 추이
# ---------------------------------------------------------------------------

def build_yearly(cur: QuarterData, prev: QuarterData, year_zips: dict[int, Path],
                  cur_year: int, prev_year: int):
    """2022~2026(확보된 것만) 6월 분기 전국 업종별(중/소분류, 이름 기준) 점포 수.

    코드 체계가 연도마다 안정적인지 100% 보장할 수 없어서(과거 분류체계 변경
    가능성) 이름을 키로 맞춘다 — 과제 지시사항 그대로.
    """
    per_year_mid: dict[int, Counter] = {}
    per_year_small: dict[int, Counter] = {}

    # 이미 메모리에 있는 현재/이전 분기는 재사용 (다시 안 읽음)
    cur_mid = Counter(r.mid_name for r in cur.records.values())
    cur_small = Counter(r.small_name for r in cur.records.values())
    prev_mid = Counter(r.mid_name for r in prev.records.values())
    prev_small = Counter(r.small_name for r in prev.records.values())
    per_year_mid[cur_year] = cur_mid
    per_year_small[cur_year] = cur_small
    per_year_mid[prev_year] = prev_mid
    per_year_small[prev_year] = prev_small

    for year, zpath in year_zips.items():
        print(f"[build-insights] {year}년 6월 분기 파싱 중: {zpath}")
        mid_c, small_c = count_by_name_only(zpath, str(year))
        per_year_mid[year] = mid_c
        per_year_small[year] = small_c

    years = sorted(per_year_mid.keys())
    all_mid_names = set()
    all_small_names = set()
    for c in per_year_mid.values():
        all_mid_names.update(c.keys())
    for c in per_year_small.values():
        all_small_names.update(c.keys())

    middle = {
        name: [per_year_mid[y].get(name, 0) for y in years]
        for name in sorted(all_mid_names)
    }
    small = {
        name: [per_year_small[y].get(name, 0) for y in years]
        for name in sorted(all_small_names)
    }

    return {"years": years, "middle": middle, "small": small}


# ---------------------------------------------------------------------------
# 크기 예산 맞추기
# ---------------------------------------------------------------------------

def _shrink_region_payload(payload: dict) -> dict:
    """region 파일이 예산(60KB)을 넘으면 순서대로 줄인다: small -> transitions -> examples -> brands."""
    def _size():
        return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    if _size() <= MAX_REGION_FILE_BYTES:
        return payload

    shrink_order = [
        ("small", 20), ("small", 10),
        ("brands", 20), ("brands", 10),
        ("transitionExamples", 15),
        ("transitions", 10),
        ("middle", 40),
    ]
    for key, limit in shrink_order:
        if _size() <= MAX_REGION_FILE_BYTES:
            break
        if key in payload and isinstance(payload[key], list) and len(payload[key]) > limit:
            payload[key] = payload[key][:limit]
    return payload


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def _parse_year_arg(value: str) -> tuple[int, Path]:
    year_s, path_s = value.split("=", 1)
    return int(year_s), Path(path_s)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--current-zip", required=True, type=Path)
    ap.add_argument("--current-quarter", required=True, help="예: 202606")
    ap.add_argument("--previous-zip", required=True, type=Path)
    ap.add_argument("--previous-quarter", required=True, help="예: 202506")
    ap.add_argument("--year", action="append", default=[], type=_parse_year_arg,
                     help="YEAR=zip경로 (예: 2024=/path/hist_20240630.zip), 여러 번 지정 가능")
    ap.add_argument("--sigungu-json", type=Path, default=Path("data/sigungu.json"))
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument(
        "--region-map", type=Path,
        default=Path(__file__).resolve().parent / "region-code-map.json",
        help="이전 분기 시군구 코드를 현재 분기 기준으로 맞추는 매핑 파일",
    )
    args = ap.parse_args()

    out_dir: Path = args.out
    (out_dir / "region").mkdir(parents=True, exist_ok=True)

    cur_year = int(args.current_quarter[:4])
    prev_year = int(args.previous_quarter[:4])
    year_zips = dict(args.year)

    print(f"[build-insights] 현재 분기 파싱: {args.current_zip} ({args.current_quarter})")
    cur = parse_quarter_full(args.current_zip, args.current_quarter)
    print(f"  -> {cur.row_count:,} rows, bad={cur.bad_rows}")

    region_map = load_region_map(args.region_map)
    cur_dong_by_sigungu: dict[str, dict[str, str]] = {}
    cur_sigungu_names: dict[str, tuple[str, str]] = {}
    for r in cur.records.values():
        cur_dong_by_sigungu.setdefault(r.sigungu_code, {})[r.dong_name] = r.dong_name
        cur_sigungu_names.setdefault(r.sigungu_code, (r.sido_name, r.sigungu_name))
    remapper = RegionRemapper(region_map, cur_dong_by_sigungu)

    print(f"[build-insights] 이전 분기 파싱: {args.previous_zip} ({args.previous_quarter}) "
          f"(시군구 코드 개편 보정 적용)")
    prev = parse_quarter_full(
        args.previous_zip, args.previous_quarter,
        remapper=remapper, cur_sigungu_names=cur_sigungu_names,
    )
    print(f"  -> {prev.row_count:,} rows, bad={prev.bad_rows}")
    if remapper.unresolved_sigungu:
        print(f"  [경고] 시군구 매칭 실패 {remapper.unresolved_sigungu}건", file=sys.stderr)

    cur_ids = set(cur.records.keys())
    prev_ids = set(prev.records.keys())
    raw_opened_ids = cur_ids - prev_ids
    raw_closed_ids = prev_ids - cur_ids
    print(f"[build-insights] raw opened={len(raw_opened_ids):,} raw closed={len(raw_closed_ids):,}")

    print("[build-insights] 번호 재부여 매칭(정규화 상호명+도로명주소+층+호) 계산 중...")
    cur_key_of = {sid: (cur.records[sid].name, cur.records[sid].road, cur.records[sid].floor, cur.records[sid].ho)
                  for sid in raw_opened_ids}
    prev_key_of = {sid: (prev.records[sid].name, prev.records[sid].road, prev.records[sid].floor, prev.records[sid].ho)
                   for sid in raw_closed_ids}
    opened_ids, closed_ids, renumbered_pairs, ambiguous_groups = resolve_opened_closed(
        cur_ids, prev_ids, cur_key_of, prev_key_of,
    )
    print(
        f"[build-insights] 재부여로 제외된 쌍: {len(renumbered_pairs):,} "
        f"(모호한 키 그룹 {ambiguous_groups:,}건) -> 2차까지 opened={len(opened_ids):,} closed={len(closed_ids):,}"
    )

    print("[build-insights] 간판 바뀜 추정 매칭(3차: 도로명주소+층+호+상권업종소분류코드) 계산 중...")
    rename_prev_only = {
        sid: (prev.records[sid].road, prev.records[sid].floor, prev.records[sid].ho, prev.records[sid].small_code)
        for sid in closed_ids
    }
    rename_cur_only = {
        sid: (cur.records[sid].road, cur.records[sid].floor, cur.records[sid].ho, cur.records[sid].small_code)
        for sid in opened_ids
    }
    renamed_prev_ids, renamed_cur_ids, renamed_pairs, renamed_excluded_both_empty, renamed_ambiguous_groups = (
        find_renamed_pairs(rename_prev_only, rename_cur_only)
    )
    opened_ids = opened_ids - renamed_cur_ids
    closed_ids = closed_ids - renamed_prev_ids
    print(
        f"  -> 간판 바뀜 추정 쌍: {len(renamed_pairs):,} "
        f"(층/호 둘다 빈값이라 제외 {renamed_excluded_both_empty:,}건, "
        f"모호한 키 그룹 {renamed_ambiguous_groups:,}건) "
        f"-> 최종 opened={len(opened_ids):,} closed={len(closed_ids):,} renamed={len(renamed_pairs):,}"
    )

    print("[build-insights] 업종 통계 계산 중...")
    nat_mid, nat_small, region_mid, region_small = build_upjong_stats(cur, prev, opened_ids, closed_ids)

    print("[build-insights] 업종 전환 계산 중...")
    # 3차("간판 바뀜 추정") 쌍은 이미 같은 자리 매칭이므로 전환 목록에서 제외한다
    # (opened_ids/closed_ids 가 이미 renamed 제외 상태라 자동으로 빠진다 — 같은
    # 업종 재입점처럼 보이는 가짜 전환/뻥튀기 방지).
    nat_transitions, matched_total, region_transitions, region_examples = build_transitions(
        cur, prev, opened_ids, closed_ids
    )
    print(f"  -> 매칭 성공 쌍: {matched_total:,}")

    print("[build-insights] 브랜드 계산 중...")
    nat_brands, region_brands, cur_brand_counter, recognized_brands = build_brands(
        cur, prev, opened_ids, closed_ids
    )

    print("[build-insights] 연도별 추이 계산 중...")
    yearly = build_yearly(cur, prev, year_zips, cur_year, prev_year)
    print(f"  -> 확보한 연도: {yearly['years']}")

    # ---- national.json ----
    national = {
        "current": args.current_quarter,
        "previous": args.previous_quarter,
        "middle": nat_mid,
        "small": nat_small,
        "transitions": nat_transitions,
        "transitionMatched": matched_total,
        "brands": nat_brands,
        "yearly": yearly,
        "renumberMatching": {
            "rawOpened": len(raw_opened_ids),
            "rawClosed": len(raw_closed_ids),
            "matchedPairs": len(renumbered_pairs),
            "ambiguousKeyGroups": ambiguous_groups,
        },
        "renameMatching": {
            "matchedPairs": len(renamed_pairs),
            "excludedBothFloorHoEmpty": renamed_excluded_both_empty,
            "ambiguousKeyGroups": renamed_ambiguous_groups,
        },
    }
    (out_dir / "national.json").write_text(json.dumps(national, ensure_ascii=False), encoding="utf-8")
    nat_size = (out_dir / "national.json").stat().st_size
    print(f"[build-insights] national.json 작성 완료 ({nat_size:,} bytes)")

    # ---- region/{code}.json ----
    sigungu_meta = json.loads(args.sigungu_json.read_text(encoding="utf-8"))
    all_region_codes = sorted({row["code"] for row in sigungu_meta})

    region_sizes = []
    for code in all_region_codes:
        payload = {
            "code": code,
            "middle": region_mid.get(code, []),
            "small": region_small.get(code, []),
            "transitions": region_transitions.get(code, []),
            "transitionExamples": region_examples.get(code, []),
            "brands": region_brands.get(code, []),
        }
        payload = _shrink_region_payload(payload)
        raw = json.dumps(payload, ensure_ascii=False)
        (out_dir / "region" / f"{code}.json").write_text(raw, encoding="utf-8")
        region_sizes.append(len(raw.encode("utf-8")))

    total_region_bytes = sum(region_sizes)
    print(f"[build-insights] region/*.json {len(all_region_codes)}개 작성 완료, "
          f"합계 {total_region_bytes:,} bytes, 최대 {max(region_sizes):,} bytes")

    total_bytes = nat_size + total_region_bytes
    print(f"[build-insights] data/insights/ 총 용량: {total_bytes:,} bytes "
          f"({total_bytes / 1024 / 1024:.2f} MB)")

    # ---- 검증용 요약 출력 ----
    print("\n=== 검증 ===")
    print(f"opened={len(opened_ids):,} closed={len(closed_ids):,}")
    print(f"closeRate 범위: "
          f"{min(r['closeRate'] for r in nat_mid):.4f} ~ {max(r['closeRate'] for r in nat_mid):.4f}")
    print(f"전환 매칭 쌍 수: {matched_total:,}")
    same_industry = sum(
        1 for r in nat_transitions if r["fromCode"] == r["toCode"]
    )
    same_industry_count = sum(
        r["count"] for r in nat_transitions if r["fromCode"] == r["toCode"]
    )
    total_top100 = sum(r["count"] for r in nat_transitions)
    print(f"전국 상위 100 전환 중 같은업종 재입점 조합 수: {same_industry}, "
          f"그 건수 비율(상위100 내): {same_industry_count / total_top100:.3f}" if total_top100 else "")

    print("\n브랜드 상위 20:")
    for b in nat_brands[:20]:
        print(f"  {b['name']:20s} stores={b['stores']:6d} prev={b['prevStores']:6d} "
              f"opened={b['opened']:5d} closed={b['closed']:5d} upjong={b['upjong']}")

    print("\n연도별 전국 총 점포 수(중분류 합):")
    for i, y in enumerate(yearly["years"]):
        total = sum(v[i] for v in yearly["middle"].values())
        print(f"  {y}: {total:,}")

    print("\n소멸률(closeRate) 최고 5개 업종(중분류, prevStores>=100):")
    eligible = [r for r in nat_mid if r["prevStores"] >= 100]
    for r in sorted(eligible, key=lambda r: -r["closeRate"])[:5]:
        print(f"  {r['name']:12s} closeRate={r['closeRate']:.3f} prevStores={r['prevStores']}")
    print("소멸률 최저 5개:")
    for r in sorted(eligible, key=lambda r: r["closeRate"])[:5]:
        print(f"  {r['name']:12s} closeRate={r['closeRate']:.3f} prevStores={r['prevStores']}")

    print("\n가장 많은 전환 조합 top5:")
    for r in nat_transitions[:5]:
        print(f"  {r['fromName']} -> {r['toName']}: {r['count']}")

    print("\n브랜드 증가 top5 / 감소 top5 (opened-closed 기준, stores>=50):")
    delta_sorted = sorted(nat_brands, key=lambda r: -(r["opened"] - r["closed"]))
    for r in delta_sorted[:5]:
        print(f"  {r['name']}: +{r['opened'] - r['closed']} (opened={r['opened']} closed={r['closed']})")
    for r in delta_sorted[-5:]:
        print(f"  {r['name']}: {r['opened'] - r['closed']} (opened={r['opened']} closed={r['closed']})")

    print("\n5년간(가능한 범위) 가장 늘어난/줄어든 소분류 top5:")
    ys = yearly["years"]
    if len(ys) >= 2:
        deltas = []
        for name, series in yearly["small"].items():
            if series[0] > 0 or series[-1] > 0:
                deltas.append((name, series[-1] - series[0], series[0], series[-1]))
        deltas.sort(key=lambda x: -x[1])
        for name, d, s0, s1 in deltas[:5]:
            print(f"  {name}: {s0} -> {s1} ({d:+d})")
        for name, d, s0, s1 in deltas[-5:]:
            print(f"  {name}: {s0} -> {s1} ({d:+d})")


if __name__ == "__main__":
    main()
