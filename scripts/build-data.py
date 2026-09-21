#!/usr/bin/env python3
"""상권나우 데이터 빌드 스크립트.

소진공 상가(상권)정보 CSV 스냅샷 2개(최신/1년전 분기)를 비교하여
앱이 정적으로 읽을 JSON 세트를 data/ 아래에 생성한다.

원본에는 "폐업" 정보가 없다(영업 중인 곳만 수록). 두 분기 스냅샷을
상가업소번호로 비교해서 신규(opened)/소멸(closed) 점포를 "추정"한다.
이 opened/closed 는 원본 API 가 제공하는 값이 아니라 이 스크립트가
분기 비교로 만들어낸 파생값이다.

사용법:
    python3 scripts/build-data.py \
        --current-zip <202606 zip 경로> --current-quarter 202606 \
        --previous-zip <202506 zip 경로> --previous-quarter 202506 \
        --out data/

pandas 등 외부 의존성 없이 표준 라이브러리만 사용한다(대용량 스트리밍
처리를 위해 zipfile + csv 를 그대로 사용, 메모리에는 필요한 컬럼만
가공해서 적재한다).

재실행 가능: zip 다운로드는 이 스크립트의 책임이 아니다(별도로 curl 로
data.go.kr 세션 쿠키를 읽어 받아둔다). 이 스크립트는 로컬에 이미 있는
zip 두 개를 읽어 data/ 를 다시 생성할 뿐이며, 여러 번 실행해도 항상
같은 결과를 만든다(idempotent).
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
from match import find_renamed_pairs, resolve_opened_closed  # noqa: E402

# ---------------------------------------------------------------------------
# CSV 스펙 (39 컬럼, 확인됨)
# ---------------------------------------------------------------------------
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
LARGE_CODE = IDX["상권업종대분류코드"]
LARGE_NAME = IDX["상권업종대분류명"]
MID_CODE = IDX["상권업종중분류코드"]
MID_NAME = IDX["상권업종중분류명"]
SMALL_CODE = IDX["상권업종소분류코드"]
SIDO_NAME = IDX["시도명"]
SIGUNGU_CODE = IDX["시군구코드"]
SIGUNGU_NAME = IDX["시군구명"]
DONG_CODE = IDX["행정동코드"]
DONG_NAME = IDX["행정동명"]
ROAD_ADDR = IDX["도로명주소"]
FLOOR = IDX["층정보"]
HO = IDX["호정보"]
LON = IDX["경도"]
LAT = IDX["위도"]

# 한반도(제주/도서 포함) 대략적 bbox. 이 범위 밖이면 좌표 이상치로 취급.
KR_LAT_RANGE = (32.5, 39.5)
KR_LON_RANGE = (124.0, 132.5)

Record = namedtuple(
    "Record",
    [
        "sigungu_code", "sigungu_name", "sido_name",
        "dong_code", "dong_name",
        "mid_code", "mid_name", "small_code", "large_code", "large_name",
        "name", "branch", "road", "floor", "ho", "lon", "lat",
    ],
)


def iv(s: str):
    """sys.intern 안전 래퍼."""
    return sys.intern(s) if s else s


class QuarterStats:
    """분기 하나를 스트리밍으로 읽으며 만드는 원시 통계/레코드 묶음."""

    def __init__(self, label: str):
        self.label = label
        self.records: dict[str, Record] = {}
        self.row_count = 0
        self.bad_field_count_rows = 0
        self.missing_coord = 0
        self.out_of_range_coord = 0
        self.sigungu_meta: dict[str, tuple[str, str]] = {}  # code -> (sido, name)
        self.dong_meta: dict[str, tuple[str, str]] = {}  # code -> (sigungu_code, name)
        self.large_meta: dict[str, str] = {}
        self.mid_meta: dict[str, tuple[str, str]] = {}  # mid_code -> (mid_name, large_code)
        self.sigungu_counter: Counter = Counter()
        self.dong_counter: Counter = Counter()
        self.dong_mid_counter: Counter = Counter()  # (dong_code, mid_code) -> count
        self.large_counter: Counter = Counter()
        self.mid_counter: Counter = Counter()
        self.sigungu_mid_counter: Counter = Counter()  # (sigungu_code, mid_code) -> count


def parse_quarter(
    zip_path: Path,
    label: str,
    remapper: RegionRemapper | None = None,
    cur_sigungu_names: dict[str, tuple[str, str]] | None = None,
) -> QuarterStats:
    """`remapper`/`cur_sigungu_names` 는 이전 분기를 파싱할 때만 넘긴다 —
    202506 스냅샷의 (전남/광주 옛 코드, 인천 중구/동구/서구, 경기 화성시) 를
    202606 기준 코드/이름으로 맞추기 위함(자세한 배경은 region_remap.py 참고)."""
    qs = QuarterStats(label)
    with zipfile.ZipFile(zip_path) as z:
        csv_members = sorted(
            n for n in z.namelist() if n.lower().endswith(".csv")
        )
        if not csv_members:
            raise SystemExit(f"[build-data] {zip_path} 안에 csv 파일이 없습니다")
        for member in csv_members:
            with z.open(member) as raw:
                tf = io.TextIOWrapper(raw, encoding="utf-8", newline="")
                reader = csv.reader(tf)
                header = next(reader)
                if len(header) != len(COLUMNS):
                    print(
                        f"[build-data][경고] {member} 헤더 컬럼 수 {len(header)} != {len(COLUMNS)}",
                        file=sys.stderr,
                    )
                for row in reader:
                    if len(row) != len(COLUMNS):
                        qs.bad_field_count_rows += 1
                        continue
                    qs.row_count += 1

                    store_id = row[ID]
                    sigungu_code = iv(row[SIGUNGU_CODE])
                    sigungu_name = iv(row[SIGUNGU_NAME])
                    sido_name = iv(row[SIDO_NAME])
                    dong_code = iv(row[DONG_CODE])
                    dong_name = iv(row[DONG_NAME])
                    mid_code = iv(row[MID_CODE])
                    mid_name = iv(row[MID_NAME])
                    small_code = iv(row[SMALL_CODE])
                    large_code = iv(row[LARGE_CODE])
                    large_name = iv(row[LARGE_NAME])
                    road = row[ROAD_ADDR]
                    floor = row[FLOOR]
                    ho = row[HO]

                    lon_raw, lat_raw = row[LON], row[LAT]
                    lon = lat = None
                    if lon_raw and lat_raw:
                        try:
                            lon = round(float(lon_raw), 6)
                            lat = round(float(lat_raw), 6)
                        except ValueError:
                            lon = lat = None
                    if lon is None or lat is None:
                        qs.missing_coord += 1
                    else:
                        if not (KR_LAT_RANGE[0] <= lat <= KR_LAT_RANGE[1]) or not (
                            KR_LON_RANGE[0] <= lon <= KR_LON_RANGE[1]
                        ):
                            qs.out_of_range_coord += 1

                    if remapper is not None and remapper.is_affected(sigungu_code):
                        new_sigungu_code = remapper.resolve_sigungu(sigungu_code, dong_name)
                        dong_code = iv(remapper.resolve_dong_code(new_sigungu_code, dong_name, dong_code))
                        sigungu_code = iv(new_sigungu_code)
                        if cur_sigungu_names and sigungu_code in cur_sigungu_names:
                            sido_name, sigungu_name = cur_sigungu_names[sigungu_code]
                            sido_name, sigungu_name = iv(sido_name), iv(sigungu_name)

                    qs.records[store_id] = Record(
                        sigungu_code, sigungu_name, sido_name,
                        dong_code, dong_name,
                        mid_code, mid_name, small_code, large_code, large_name,
                        row[NAME], row[BRANCH], road, floor, ho, lon, lat,
                    )

                    qs.sigungu_meta.setdefault(sigungu_code, (sido_name, sigungu_name))
                    qs.dong_meta.setdefault(dong_code, (sigungu_code, dong_name))
                    qs.large_meta.setdefault(large_code, large_name)
                    qs.mid_meta.setdefault(mid_code, (mid_name, large_code))

                    qs.sigungu_counter[sigungu_code] += 1
                    qs.dong_counter[dong_code] += 1
                    qs.dong_mid_counter[(dong_code, mid_code)] += 1
                    qs.large_counter[large_code] += 1
                    qs.mid_counter[mid_code] += 1
                    qs.sigungu_mid_counter[(sigungu_code, mid_code)] += 1
    return qs


# ---------------------------------------------------------------------------
# 검증 / 정합성 체크
# ---------------------------------------------------------------------------

def run_sanity_checks(cur: QuarterStats, prev: QuarterStats) -> dict:
    cur_ids = set(cur.records.keys())
    prev_ids = set(prev.records.keys())
    common = cur_ids & prev_ids

    intersection_ratio_vs_prev = len(common) / len(prev_ids) if prev_ids else 0.0
    intersection_ratio_vs_cur = len(common) / len(cur_ids) if cur_ids else 0.0

    cur_dong_codes = set(cur.dong_meta.keys())
    prev_dong_codes = set(prev.dong_meta.keys())
    dong_only_cur = cur_dong_codes - prev_dong_codes
    dong_only_prev = prev_dong_codes - cur_dong_codes
    dong_common = cur_dong_codes & prev_dong_codes

    checks = {
        "id_intersection": {
            "common": len(common),
            "prev_total": len(prev_ids),
            "cur_total": len(cur_ids),
            "ratio_vs_prev": round(intersection_ratio_vs_prev, 4),
            "ratio_vs_cur": round(intersection_ratio_vs_cur, 4),
        },
        "dong_code_scheme": {
            "cur_dong_codes": len(cur_dong_codes),
            "prev_dong_codes": len(prev_dong_codes),
            "common": len(dong_common),
            "only_in_cur": len(dong_only_cur),
            "only_in_prev": len(dong_only_prev),
            "sample_only_in_cur": sorted(dong_only_cur)[:10],
            "sample_only_in_prev": sorted(dong_only_prev)[:10],
        },
        "coords": {
            "cur": {
                "rows": cur.row_count,
                "missing": cur.missing_coord,
                "missing_pct": round(cur.missing_coord / cur.row_count * 100, 3) if cur.row_count else 0,
                "out_of_range": cur.out_of_range_coord,
                "out_of_range_pct": round(cur.out_of_range_coord / cur.row_count * 100, 3) if cur.row_count else 0,
            },
            "prev": {
                "rows": prev.row_count,
                "missing": prev.missing_coord,
                "missing_pct": round(prev.missing_coord / prev.row_count * 100, 3) if prev.row_count else 0,
                "out_of_range": prev.out_of_range_coord,
                "out_of_range_pct": round(prev.out_of_range_coord / prev.row_count * 100, 3) if prev.row_count else 0,
            },
        },
        "encoding": "utf-8 (모든 행 utf-8 strict 디코딩 성공, 깨진 행 없음)",
        "malformed_rows": {"cur": cur.bad_field_count_rows, "prev": prev.bad_field_count_rows},
    }
    return checks, cur_ids, prev_ids, common


# ---------------------------------------------------------------------------
# 산출물 빌더
# ---------------------------------------------------------------------------

def build_sigungu_json(cur: QuarterStats, prev: QuarterStats, opened_ids, closed_ids, renamed_cur_ids):
    opened_by_sigungu = Counter()
    closed_by_sigungu = Counter()
    renamed_by_sigungu = Counter()
    for sid in opened_ids:
        opened_by_sigungu[cur.records[sid].sigungu_code] += 1
    for sid in closed_ids:
        closed_by_sigungu[prev.records[sid].sigungu_code] += 1
    for sid in renamed_cur_ids:
        renamed_by_sigungu[cur.records[sid].sigungu_code] += 1

    all_codes = set(cur.sigungu_meta) | set(prev.sigungu_meta)
    rows = []
    for code in all_codes:
        sido, name = cur.sigungu_meta.get(code) or prev.sigungu_meta.get(code)
        stores = cur.sigungu_counter.get(code, 0)
        prev_stores = prev.sigungu_counter.get(code, 0)
        opened = opened_by_sigungu.get(code, 0)
        closed = closed_by_sigungu.get(code, 0)
        renamed = renamed_by_sigungu.get(code, 0)
        turnover = round((opened + closed) / prev_stores, 3) if prev_stores else 0.0
        rows.append({
            "code": code,
            "sido": sido,
            "name": name,
            "stores": stores,
            "prevStores": prev_stores,
            "opened": opened,
            "closed": closed,
            "renamed": renamed,
            "turnoverRate": turnover,
        })
    rows.sort(key=lambda r: r["code"])
    return rows, opened_by_sigungu, closed_by_sigungu


def build_dong_files(cur: QuarterStats, prev: QuarterStats, opened_ids, closed_ids, renamed_cur_ids, out_dir: Path):
    opened_by_dong = Counter()
    closed_by_dong = Counter()
    renamed_by_dong = Counter()
    for sid in opened_ids:
        opened_by_dong[cur.records[sid].dong_code] += 1
    for sid in closed_ids:
        closed_by_dong[prev.records[sid].dong_code] += 1
    for sid in renamed_cur_ids:
        renamed_by_dong[cur.records[sid].dong_code] += 1

    # sigungu_code -> [dong rows]
    by_sigungu: dict[str, list[dict]] = defaultdict(list)
    all_dong_codes = set(cur.dong_meta) | set(prev.dong_meta)
    for dong_code in all_dong_codes:
        meta = cur.dong_meta.get(dong_code) or prev.dong_meta.get(dong_code)
        sigungu_code, dong_name = meta
        stores = cur.dong_counter.get(dong_code, 0)
        prev_stores = prev.dong_counter.get(dong_code, 0)
        opened = opened_by_dong.get(dong_code, 0)
        closed = closed_by_dong.get(dong_code, 0)
        renamed = renamed_by_dong.get(dong_code, 0)
        turnover = round((opened + closed) / prev_stores, 3) if prev_stores else 0.0

        # top 8 업종중분류 (현재 개수 내림차순), delta = 현재 - 이전
        mid_cur_counts = {
            mid: c for (d, mid), c in cur.dong_mid_counter.items() if d == dong_code
        }
        top_codes = sorted(mid_cur_counts.items(), key=lambda kv: -kv[1])[:8]
        top = []
        for mid_code, count in top_codes:
            mid_name = (cur.mid_meta.get(mid_code) or prev.mid_meta.get(mid_code) or (mid_code, None))[0]
            prev_count = prev.dong_mid_counter.get((dong_code, mid_code), 0)
            top.append({
                "code": mid_code,
                "name": mid_name,
                "count": count,
                "delta": count - prev_count,
            })

        by_sigungu[sigungu_code].append({
            "code": dong_code,
            "name": dong_name,
            "stores": stores,
            "prevStores": prev_stores,
            "opened": opened,
            "closed": closed,
            "renamed": renamed,
            "turnoverRate": turnover,
            "top": top,
        })

    out_dir.mkdir(parents=True, exist_ok=True)
    for sigungu_code, dong_rows in by_sigungu.items():
        dong_rows.sort(key=lambda r: r["code"])
        (out_dir / f"{sigungu_code}.json").write_text(
            json.dumps(dong_rows, ensure_ascii=False), encoding="utf-8"
        )
    return len(by_sigungu)


def build_upjong_json(cur: QuarterStats, prev: QuarterStats):
    large_rows = []
    all_large = set(cur.large_meta) | set(prev.large_meta)
    for code in all_large:
        name = cur.large_meta.get(code) or prev.large_meta.get(code)
        stores = cur.large_counter.get(code, 0)
        prev_stores = prev.large_counter.get(code, 0)
        large_rows.append({
            "code": code, "name": name, "stores": stores, "delta": stores - prev_stores,
        })
    large_rows.sort(key=lambda r: -r["stores"])

    mid_rows = []
    all_mid = set(cur.mid_meta) | set(prev.mid_meta)
    for code in all_mid:
        mid_name, large_code = cur.mid_meta.get(code) or prev.mid_meta.get(code)
        stores = cur.mid_counter.get(code, 0)
        prev_stores = prev.mid_counter.get(code, 0)
        mid_rows.append({
            "code": code, "name": mid_name, "largeCode": large_code,
            "stores": stores, "delta": stores - prev_stores,
        })
    mid_rows.sort(key=lambda r: -r["stores"])

    return {"large": large_rows, "middle": mid_rows}


def build_rank_files(cur: QuarterStats, upjong: dict, out_dir: Path, top_n_upjong: int = 30, top_n_sigungu: int = 50):
    out_dir.mkdir(parents=True, exist_ok=True)
    top_mid = upjong["middle"][:top_n_upjong]
    for mid in top_mid:
        code = mid["code"]
        rows = []
        for (sigungu_code, mc), count in cur.sigungu_mid_counter.items():
            if mc != code or count <= 0:
                continue
            sido, name = cur.sigungu_meta.get(sigungu_code, (None, None))
            rows.append({
                "sigunguCode": sigungu_code, "sido": sido, "name": name, "stores": count,
            })
        rows.sort(key=lambda r: -r["stores"])
        rows = rows[:top_n_sigungu]
        payload = {"code": code, "name": mid["name"], "rows": rows}
        (out_dir / f"upjong-{code}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    return len(top_mid)


def _change_item(record: Record) -> dict:
    item = {
        "name": record.name,
        "upjong": record.mid_name,
        "dong": record.dong_name,
        "road": record.road,
        "lat": record.lat,
        "lon": record.lon,
    }
    if record.branch:
        item["branch"] = record.branch
    return item


def build_changes_files(cur: QuarterStats, prev: QuarterStats, opened_ids, closed_ids, out_dir: Path, max_bytes: int = 350_000):
    out_dir.mkdir(parents=True, exist_ok=True)

    opened_by_sigungu: dict[str, list[str]] = defaultdict(list)
    for sid in opened_ids:
        opened_by_sigungu[cur.records[sid].sigungu_code].append(sid)
    closed_by_sigungu: dict[str, list[str]] = defaultdict(list)
    for sid in closed_ids:
        closed_by_sigungu[prev.records[sid].sigungu_code].append(sid)

    all_codes = set(opened_by_sigungu) | set(closed_by_sigungu) | set(cur.sigungu_meta) | set(prev.sigungu_meta)

    for code in all_codes:
        opened_sids = opened_by_sigungu.get(code, [])
        closed_sids = closed_by_sigungu.get(code, [])

        opened_items = [_change_item(cur.records[sid]) for sid in opened_sids]
        closed_items = [_change_item(prev.records[sid]) for sid in closed_sids]

        payload = {
            "opened": opened_items,
            "closed": closed_items,
            "openedTotal": len(opened_items),
            "closedTotal": len(closed_items),
        }
        raw = json.dumps(payload, ensure_ascii=False)
        if len(raw.encode("utf-8")) > max_bytes:
            # 90% 안전마진을 두고 행정동별로 고르게 샘플링한다.
            budget = int(max_bytes * 0.9)
            payload["opened"] = _sample_by_dong(opened_items, budget // 2)
            payload["closed"] = _sample_by_dong(closed_items, budget // 2)
            raw = json.dumps(payload, ensure_ascii=False)
            # 그래도 초과하면 균등 절삭으로 강제로 맞춘다.
            while len(raw.encode("utf-8")) > max_bytes and (payload["opened"] or payload["closed"]):
                if len(payload["opened"]) > len(payload["closed"]):
                    payload["opened"] = payload["opened"][: max(0, len(payload["opened"]) - max(1, len(payload["opened"]) // 10))]
                else:
                    payload["closed"] = payload["closed"][: max(0, len(payload["closed"]) - max(1, len(payload["closed"]) // 10))]
                raw = json.dumps(payload, ensure_ascii=False)
        (out_dir / f"{code}.json").write_text(raw, encoding="utf-8")

    return len(all_codes)


def _sample_by_dong(items: list[dict], budget_bytes: int) -> list[dict]:
    if not items:
        return items
    avg_item_bytes = max(1, len(json.dumps(items[0], ensure_ascii=False).encode("utf-8")))
    target_n = max(1, budget_bytes // avg_item_bytes)
    if target_n >= len(items):
        return items

    by_dong: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_dong[it["dong"]].append(it)

    dong_keys = list(by_dong.keys())
    ratio = target_n / len(items)
    sampled = []
    for k in dong_keys:
        bucket = by_dong[k]
        n = max(1, round(len(bucket) * ratio))
        sampled.extend(bucket[:n])
    return sampled[:target_n]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--current-zip", required=True, type=Path)
    ap.add_argument("--current-quarter", required=True)
    ap.add_argument("--previous-zip", required=True, type=Path)
    ap.add_argument("--previous-quarter", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--source-note", default="")
    ap.add_argument(
        "--region-map", type=Path,
        default=Path(__file__).resolve().parent / "region-code-map.json",
        help="이전 분기 시군구/행정동 코드를 현재 분기 기준으로 맞추는 매핑 파일",
    )
    args = ap.parse_args()

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[build-data] 최신 분기 파싱: {args.current_zip} ({args.current_quarter})")
    cur = parse_quarter(args.current_zip, args.current_quarter)
    print(f"  -> {cur.row_count:,} rows, malformed={cur.bad_field_count_rows}")

    region_map = load_region_map(args.region_map)
    cur_dong_by_sigungu = build_cur_dong_index(cur.dong_meta)
    remapper = RegionRemapper(region_map, cur_dong_by_sigungu)

    print(f"[build-data] 이전 분기 파싱: {args.previous_zip} ({args.previous_quarter}) "
          f"(시군구/행정동 코드 개편 보정 적용)")
    prev = parse_quarter(
        args.previous_zip, args.previous_quarter,
        remapper=remapper, cur_sigungu_names=cur.sigungu_meta,
    )
    if remapper.unresolved_sigungu or remapper.unresolved_dong:
        print(
            f"  [경고] 코드 개편 보정: 시군구 매칭 실패 {remapper.unresolved_sigungu}건, "
            f"행정동 매칭 실패(시군구는 맞음) {remapper.unresolved_dong}건",
            file=sys.stderr,
        )
    print(f"  -> {prev.row_count:,} rows, malformed={prev.bad_field_count_rows}")

    print("[build-data] 정합성 체크 계산 중...")
    checks, cur_ids, prev_ids, common_ids = run_sanity_checks(cur, prev)
    raw_opened_ids = cur_ids - prev_ids
    raw_closed_ids = prev_ids - cur_ids
    print(f"  -> raw opened={len(raw_opened_ids):,} raw closed={len(raw_closed_ids):,} common={len(common_ids):,}")

    print("[build-data] 번호 재부여 매칭(정규화 상호명+도로명주소+층+호) 계산 중...")
    cur_key_of = {sid: (cur.records[sid].name, cur.records[sid].road, cur.records[sid].floor, cur.records[sid].ho)
                  for sid in raw_opened_ids}
    prev_key_of = {sid: (prev.records[sid].name, prev.records[sid].road, prev.records[sid].floor, prev.records[sid].ho)
                   for sid in raw_closed_ids}
    opened_ids, closed_ids, renumbered_pairs, ambiguous_groups = resolve_opened_closed(
        cur_ids, prev_ids, cur_key_of, prev_key_of,
    )
    print(
        f"  -> 재부여로 판정되어 제외된 쌍: {len(renumbered_pairs):,} "
        f"(모호한 키 그룹 {ambiguous_groups:,}건은 1:1로만 매칭)"
    )
    print(f"  -> 2차까지 opened={len(opened_ids):,} closed={len(closed_ids):,}")

    print("[build-data] 간판 바뀜 추정 매칭(3차: 도로명주소+층+호+상권업종소분류코드) 계산 중...")
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
    final_opened_ids = opened_ids - renamed_cur_ids
    final_closed_ids = closed_ids - renamed_prev_ids
    print(
        f"  -> 간판 바뀜 추정 쌍: {len(renamed_pairs):,} "
        f"(층/호 둘다 빈값이라 제외 {renamed_excluded_both_empty:,}건, "
        f"모호한 키 그룹 {renamed_ambiguous_groups:,}건)"
    )
    print(f"  -> 최종 opened={len(final_opened_ids):,} closed={len(final_closed_ids):,} renamed={len(renamed_pairs):,}")

    print("[build-data] sigungu.json 생성 중...")
    sigungu_rows, opened_by_sigungu, closed_by_sigungu = build_sigungu_json(
        cur, prev, final_opened_ids, final_closed_ids, renamed_cur_ids,
    )
    (out_dir / "sigungu.json").write_text(json.dumps(sigungu_rows, ensure_ascii=False), encoding="utf-8")

    print("[build-data] dong/*.json 생성 중...")
    dong_count = build_dong_files(cur, prev, final_opened_ids, final_closed_ids, renamed_cur_ids, out_dir / "dong")

    print("[build-data] upjong.json 생성 중...")
    upjong = build_upjong_json(cur, prev)
    (out_dir / "upjong.json").write_text(json.dumps(upjong, ensure_ascii=False), encoding="utf-8")

    print("[build-data] rank/*.json 생성 중...")
    rank_count = build_rank_files(cur, upjong, out_dir / "rank")

    print("[build-data] changes/*.json 생성 중...")
    changes_count = build_changes_files(cur, prev, final_opened_ids, final_closed_ids, out_dir / "changes")

    totals = {
        "stores": cur.row_count,
        "prevStores": prev.row_count,
        "opened": len(final_opened_ids),
        "closed": len(final_closed_ids),
        "renamed": len(renamed_pairs),
    }
    checks["renumberMatching"] = {
        "rawOpened": len(raw_opened_ids),
        "rawClosed": len(raw_closed_ids),
        "matchedPairs": len(renumbered_pairs),
        "ambiguousKeyGroups": ambiguous_groups,
        "note": (
            "1차(상가업소번호) 매칭에서 짝을 못 찾은 것들끼리 (정규화 상호명, 도로명주소, "
            "층, 호) 키로 2차 매칭 — 같은 가게가 번호만 재부여된 경우를 신규/소멸 양쪽에서 "
            "제외한다(scripts/match.py 참고)."
        ),
    }
    checks["renameMatching"] = {
        "matchedPairs": len(renamed_pairs),
        "excludedBothFloorHoEmpty": renamed_excluded_both_empty,
        "ambiguousKeyGroups": renamed_ambiguous_groups,
        "note": (
            "1·2차 매칭에서도 짝을 못 찾은 소멸/신규 중 (도로명주소, 층, 호, 상권업종소분류코드)가 "
            "같고 그 키 안에서 소멸 1개·신규 1개인 1:1 쌍만 '간판 바뀜 추정(renamed)'으로 보고 "
            "opened/closed 에서 제외한다(scripts/match.py 참고). 추정이며, 실제로는 같은 자리에서 "
            "업종만 같은 별개 점포로 교체됐을 가능성도 있다."
        ),
    }
    meta = {
        "current": args.current_quarter,
        "previous": args.previous_quarter,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "totals": totals,
        "sourceNote": args.source_note or (
            "소진공 상가(상권)정보 분기 스냅샷 두 개(최신/이전)를 상가업소번호로 비교해 "
            "opened/closed 를 추정한 파생 데이터. 원본에는 폐업 정보가 없음. 상가업소번호가 "
            "재부여된 경우(같은 가게, 번호만 바뀜)는 (정규화 상호명, 도로명주소, 층, 호) "
            "2차 매칭으로 걸러내 신규/소멸 이중 계산을 줄인다. 상호명까지 함께 바뀐 경우(간판 "
            "바뀜 추정)는 (도로명주소, 층, 호, 상권업종소분류코드) 3차 매칭으로 걸러 별도로 "
            "renamed 로 센다(추정치, 알려진 한계 있음 — sanityChecks.renameMatching 참고)."
        ),
        "sanityChecks": checks,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 요약 ===")
    print(json.dumps(totals, ensure_ascii=False, indent=2))
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    print(f"sigungu rows: {len(sigungu_rows)}")
    print(f"dong files: {dong_count}")
    print(f"rank files: {rank_count}")
    print(f"changes files: {changes_count}")


if __name__ == "__main__":
    main()
