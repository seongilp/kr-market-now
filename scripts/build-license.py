#!/usr/bin/env python3
"""소진공 상가(상권)정보 식품접객업 계열 점포 <-> 식약처 인허가(I1200) 조인.

배경: 소진공 상가정보는 원본에 폐업 정보가 없어 opened/closed 를 분기
스냅샷 비교로 "추정"한다(scripts/build-data.py, scripts/match.py). 그런데
식약처/지방행정 인허가데이터는 인허가일자·폐업일자가 명시돼 있어 실제
개폐업 시점을 알 수 있다 — 소진공 등록이 늦게 반영되는 경우(예: 스타벅스
철산역점, 식약처 허가일 2019-10-22 인데 소진공 202603 회차까지 등장 안 함)
"신규"로 오판될 수 있고, 반대로 실제로는 폐업했는데 소진공에 아직 남아있어
"소멸" 판정이 늦어질 수도 있다. 이 스크립트는 그 격차를 정량화한다.

데이터 소스 조사 결과(2026-09-21, 이 스크립트 작성 시점):
  - localdata.go.kr(지방행정인허가데이터 "전체 데이터 다운로드")는 이 실행
    환경에서 curl/헤드리스 브라우저 모두 TLS 핸드셰이크 전에 연결 타임아웃
    — DNS는 풀리지만(152.99.104.122) 접속이 막혀 있어 접근 불가로 판단.
  - data.go.kr 의 "식품접객업" 파일데이터는 전국 단일 파일이 아니라
    시군구별로 쪼개져 올라와 있다(예: "인천광역시_연수구_식품접객업 현황",
    "부산광역시_금정구_식품접객업 현황" ...) — 전국을 받으려면 수백 건을
    개별 신청/다운로드해야 해서 API 경로보다 느리다.
  - 그래서 식품안전나라 오픈API I1200(식품접객업정보)을 썼다. 이미 이전
    세션에서 활용신청이 승인돼 있었다(scripts/../scratchpad 흔적 참고).
    1회 최대 1,000건, 하루 호출 한도가 있어 scripts/../scratchpad 아래
    fetch_i1200.py 가 진행 상태를 저장하며 여러 날에 걸쳐 이어받는다
    (이 조인 스크립트와는 별도 실행 — README 대신 이 주석 및 최종 보고 참고).
  - **좌표계**: I1200 의 SITE_X/SITE_Y 는 이름과 달리 TM(중부원점)이 아니라
    이미 WGS84 경도/위도였다(실측: 장수식당 SITE_X=126.6468694,
    SITE_Y=37.4652466 — 인천 미추홀구 범위와 일치). pyproj 변환 불필요.
  - **주소 한계**: I1200 오픈API 의 LOCP_ADDR 은 시군구 수준까지만 내려온다
    (예: "경기도 광명시" — 도로명·층·호 없음, 개인정보 마스킹으로 추정).
    그래서 과제에서 제시한 매칭 키 ①(정규화 상호명+도로명주소)과
    ③(도로명주소+층/호 단독)은 이 데이터로는 애초에 불가능하다. 실질적으로
    가능한 건 ②(정규화 상호명 + 좌표 근접)뿐이다 — 이 스크립트는 ②만
    구현한다(이 사실 자체가 조사 결과이자 한계).

사용법:
    python3 scripts/build-license.py \
        --current-zip <202606 zip> --current-quarter 202606 \
        --previous-zip <202506 zip> --previous-quarter 202506 \
        --i1200-ndjson <scratchpad>/localdata/i1200_raw.ndjson \
        --out-dir <scratchpad>/license-join \
        [--radius-m 50] [--sample-json <path>]

출력(모두 scratchpad, 리포에는 커밋 안 함):
  - <out-dir>/store_license_map.ndjson : 상가업소번호 -> {허가일, 폐업일,
    영업상태, 인허가관리번호(BSN_LCNS_LEDG_NO), 매칭방식, 거리m}
  - <out-dir>/report.json : 정량화 결과(질문 3의 표)
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from region_remap import RegionRemapper, build_cur_dong_index, load_region_map  # noqa: E402
from match import find_renamed_pairs, resolve_opened_closed  # noqa: E402
from normalize import normalize_brand, brand_is_noise  # noqa: E402

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


class Store:
    __slots__ = (
        "sid", "name", "branch", "large_code", "small_code", "small_name",
        "sigungu_code", "sigungu_name", "sido_name", "road", "floor", "ho",
        "lon", "lat",
    )

    def __init__(self, row, sigungu_code, sido_name, sigungu_name):
        self.sid = row[IDX["상가업소번호"]]
        self.name = row[IDX["상호명"]]
        self.branch = row[IDX["지점명"]]
        self.large_code = sys.intern(row[IDX["상권업종대분류코드"]])
        self.small_code = sys.intern(row[IDX["상권업종소분류코드"]])
        self.small_name = row[IDX["상권업종소분류명"]]
        self.sigungu_code = sigungu_code
        self.sigungu_name = sigungu_name
        self.sido_name = sido_name
        self.road = row[IDX["도로명주소"]]
        self.floor = row[IDX["층정보"]]
        self.ho = row[IDX["호정보"]]
        lon_raw, lat_raw = row[IDX["경도"]], row[IDX["위도"]]
        try:
            self.lon = float(lon_raw) if lon_raw else None
            self.lat = float(lat_raw) if lat_raw else None
        except ValueError:
            self.lon, self.lat = None, None


def parse_quarter(zip_path: Path, remapper: RegionRemapper | None, cur_sigungu_names=None):
    """build-data.py 의 parse_quarter 를 이 스크립트에 필요한 필드만 남겨 재구현."""
    records: dict[str, Store] = {}
    dong_meta: dict[str, tuple[str, str]] = {}
    row_count = 0
    with zipfile.ZipFile(zip_path) as z:
        members = sorted(n for n in z.namelist() if n.lower().endswith(".csv"))
        if not members:
            raise SystemExit(f"[build-license] {zip_path} 안에 csv 없음")
        for member in members:
            with z.open(member) as raw:
                tf = io.TextIOWrapper(raw, encoding="utf-8", newline="")
                reader = csv.reader(tf)
                header = next(reader)
                if len(header) != len(COLUMNS):
                    print(f"[build-license][경고] {member} 헤더 컬럼 수 불일치", file=sys.stderr)
                for row in reader:
                    if len(row) != len(COLUMNS):
                        continue
                    row_count += 1
                    sigungu_code = row[IDX["시군구코드"]]
                    sido_name = row[IDX["시도명"]]
                    sigungu_name = row[IDX["시군구명"]]
                    dong_code = row[IDX["행정동코드"]]
                    dong_name = row[IDX["행정동명"]]

                    if remapper is not None and remapper.is_affected(sigungu_code):
                        new_sigungu_code = remapper.resolve_sigungu(sigungu_code, dong_name)
                        sigungu_code = new_sigungu_code
                        if cur_sigungu_names and sigungu_code in cur_sigungu_names:
                            sido_name, sigungu_name = cur_sigungu_names[sigungu_code]

                    st = Store(row, sigungu_code, sido_name, sigungu_name)
                    records[st.sid] = st
                    dong_meta.setdefault(dong_code, (sigungu_code, dong_name))
    return records, dong_meta, row_count


def haversine_m(lon1, lat1, lon2, lat2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_i1200(ndjson_path: Path):
    """I1200 레코드를 (정규화 상호명) -> [행] 인덱스로 적재.

    각 행: dict(lcns_no, bssh_nm, norm, lon, lat, prms_dt, clsbiz_dt, INDUTY_NM)
    좌표가 없거나(빈 문자열) 대한민국 bbox 밖이면 매칭 후보에서 제외.
    """
    by_name: dict[str, list[dict]] = defaultdict(list)
    total = 0
    no_coord = 0
    with open(ndjson_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            total += 1
            sx, sy = r.get("SITE_X", ""), r.get("SITE_Y", "")
            try:
                lon, lat = float(sx), float(sy)
            except (ValueError, TypeError):
                no_coord += 1
                continue
            if not (124.0 <= lon <= 132.5 and 32.5 <= lat <= 39.5):
                no_coord += 1
                continue
            norm = normalize_brand(r.get("BSSH_NM", ""))
            if brand_is_noise(norm):
                continue
            by_name[norm].append({
                "lcns_no": r.get("BSN_LCNS_LEDG_NO") or r.get("LCNS_NO"),
                "name": r.get("BSSH_NM"),
                "lon": lon, "lat": lat,
                "prms_dt": r.get("PRMS_DT") or None,
                "clsbiz_dt": r.get("CLSBIZ_DT") or None,
                "induty": r.get("INDUTY_NM"),
                "locp_addr": r.get("LOCP_ADDR"),
            })
    return by_name, total, no_coord


def match_store(store: Store, i1200_by_name: dict, radius_m: float):
    if store.lon is None or store.lat is None:
        return None
    norm = normalize_brand(store.name)
    if brand_is_noise(norm):
        return None
    candidates = i1200_by_name.get(norm)
    if not candidates:
        return None
    best = None
    best_d = None
    for c in candidates:
        d = haversine_m(store.lon, store.lat, c["lon"], c["lat"])
        if d <= radius_m and (best_d is None or d < best_d):
            best_d = d
            best = c
    if best is None:
        return None
    return best, best_d


def parse_ymd(s: str | None):
    if not s or len(s) != 8:
        return None
    try:
        return int(s)  # YYYYMMDD as int, sortable
    except ValueError:
        return None


def bucket_year(prms_dt_int: int | None) -> str:
    if prms_dt_int is None:
        return "unknown"
    y = prms_dt_int // 10000
    if y < 2020:
        return "2019이전"
    if 2020 <= y <= 2024:
        return "2020~2024"
    if prms_dt_int < 20250701:
        return "2025H1"
    return "2025H2~2026"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--current-zip", required=True, type=Path)
    ap.add_argument("--current-quarter", required=True)
    ap.add_argument("--previous-zip", required=True, type=Path)
    ap.add_argument("--previous-quarter", required=True)
    ap.add_argument("--i1200-ndjson", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--radius-m", type=float, default=50.0)
    ap.add_argument(
        "--region-map", type=Path,
        default=Path(__file__).resolve().parent / "region-code-map.json",
    )
    ap.add_argument("--food-large-code", default="I2", help="식품접객업 계열로 볼 상권업종대분류코드")
    args = ap.parse_args()

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[build-license] 최신 분기 파싱: {args.current_zip}")
    cur, cur_dong_meta, cur_row_count = parse_quarter(args.current_zip, None)
    print(f"  -> {cur_row_count:,} rows")

    region_map = load_region_map(args.region_map)
    cur_dong_by_sigungu = build_cur_dong_index(cur_dong_meta)
    remapper = RegionRemapper(region_map, cur_dong_by_sigungu)

    print(f"[build-license] 이전 분기 파싱: {args.previous_zip} (코드 개편 보정)")
    cur_sigungu_names = {}
    for st in cur.values():
        cur_sigungu_names.setdefault(st.sigungu_code, (st.sido_name, st.sigungu_name))
    prev, prev_dong_meta, prev_row_count = parse_quarter(
        args.previous_zip, remapper, cur_sigungu_names=cur_sigungu_names,
    )
    print(f"  -> {prev_row_count:,} rows")

    print("[build-license] opened/closed 재현(match.py 1~4차 동일 로직)...")
    cur_ids = set(cur.keys())
    prev_ids = set(prev.keys())
    raw_opened_ids = cur_ids - prev_ids
    raw_closed_ids = prev_ids - cur_ids

    cur_key_of = {sid: (cur[sid].name, cur[sid].road, cur[sid].floor, cur[sid].ho) for sid in raw_opened_ids}
    prev_key_of = {sid: (prev[sid].name, prev[sid].road, prev[sid].floor, prev[sid].ho) for sid in raw_closed_ids}
    opened_ids, closed_ids, renumbered_pairs, amb1 = resolve_opened_closed(cur_ids, prev_ids, cur_key_of, prev_key_of)

    rename_prev_only = {sid: (prev[sid].road, prev[sid].floor, prev[sid].ho, prev[sid].small_code) for sid in closed_ids}
    rename_cur_only = {sid: (cur[sid].road, cur[sid].floor, cur[sid].ho, cur[sid].small_code) for sid in opened_ids}
    prev_addr_counts = Counter(st.road for st in prev.values() if st.road)
    cur_addr_counts = Counter(st.road for st in cur.values() if st.road)
    renamed_prev_ids, renamed_cur_ids, renamed_pairs, _excl, _amb2, _tier4 = find_renamed_pairs(
        rename_prev_only, rename_cur_only, prev_addr_counts, cur_addr_counts,
    )
    final_opened_ids = opened_ids - renamed_cur_ids
    final_closed_ids = closed_ids - renamed_prev_ids
    print(f"  -> final opened={len(final_opened_ids):,} closed={len(final_closed_ids):,} "
          f"(참고: data/meta.json 은 opened=362393 closed=287247 이어야 일치)")

    food_code = args.food_large_code
    opened_food_ids = [sid for sid in final_opened_ids if cur[sid].large_code == food_code]
    closed_food_ids = [sid for sid in final_closed_ids if prev[sid].large_code == food_code]
    print(f"  -> 식품접객업({food_code}) 신규={len(opened_food_ids):,} 소멸={len(closed_food_ids):,}")

    print(f"[build-license] I1200 적재: {args.i1200_ndjson}")
    i1200_by_name, i1200_total, i1200_no_coord = load_i1200(args.i1200_ndjson)
    print(f"  -> I1200 rows={i1200_total:,} (좌표 없음/범위밖 제외={i1200_no_coord:,}, "
          f"이름 정규화 후 고유 키={len(i1200_by_name):,})")

    print(f"[build-license] 좌표 매칭 (반경 {args.radius_m}m)...")

    def match_set(ids, snapshot):
        matched = []
        unmatched = 0
        for sid in ids:
            st = snapshot[sid]
            res = match_store(st, i1200_by_name, args.radius_m)
            if res is None:
                unmatched += 1
                continue
            c, d = res
            matched.append((sid, st, c, d))
        return matched, unmatched

    opened_matched, opened_unmatched = match_set(opened_food_ids, cur)
    closed_matched, closed_unmatched = match_set(closed_food_ids, prev)
    print(f"  -> 신규 매칭 {len(opened_matched):,}/{len(opened_food_ids):,} "
          f"({len(opened_matched)/max(1,len(opened_food_ids))*100:.1f}%)")
    print(f"  -> 소멸 매칭 {len(closed_matched):,}/{len(closed_food_ids):,} "
          f"({len(closed_matched)/max(1,len(closed_food_ids))*100:.1f}%)")

    # ---- 정량화 ----
    cur_snapshot_date = int(f"{args.current_quarter}30") if args.current_quarter.endswith("06") else None
    # 202606 스냅샷 "최신" 시점 = 2026-06-30 로 취급(질문 3의 "허가일이 2025-06-30 이전" 기준용 X,
    # 실제 요청은 "2025-06-30 이전 = 등록 지연으로 신규 오판" 이므로 고정 임계값 사용.
    LATE_REG_THRESHOLD = 20250630

    opened_pre_threshold = sum(1 for _sid, _st, c, _d in opened_matched
                                if (p := parse_ymd(c["prms_dt"])) is not None and p <= LATE_REG_THRESHOLD)
    opened_year_dist = Counter(bucket_year(parse_ymd(c["prms_dt"])) for _sid, _st, c, _d in opened_matched)

    closed_still_open = sum(1 for _sid, _st, c, _d in closed_matched if not c["clsbiz_dt"])
    closed_clsbiz_dist = Counter()
    for _sid, _st, c, _d in closed_matched:
        cd = c["clsbiz_dt"]
        if not cd:
            closed_clsbiz_dist["영업중(폐업일 없음)"] += 1
        else:
            y = cd[:4]
            if y < "2020":
                closed_clsbiz_dist["2019이전"] += 1
            elif y <= "2024":
                closed_clsbiz_dist["2020~2024"] += 1
            elif cd < "20250701":
                closed_clsbiz_dist["2025H1"] += 1
            else:
                closed_clsbiz_dist["2025H2~2026"] += 1

    # I1200 자체 기준 2025-07~2026-06 허가/폐업 건수(전체 I1200, 식품접객업 전체)
    window_lo, window_hi = 20250701, 20260630
    i1200_licensed_in_window = 0
    i1200_closed_in_window = 0
    i1200_all = 0
    for name_bucket in i1200_by_name.values():
        for r in name_bucket:
            i1200_all += 1
            p = parse_ymd(r["prms_dt"])
            if p is not None and window_lo <= p <= window_hi:
                i1200_licensed_in_window += 1
            cd = parse_ymd(r["clsbiz_dt"])
            if cd is not None and window_lo <= cd <= window_hi:
                i1200_closed_in_window += 1

    # 스타벅스 철산역 사례 추적 (실제 상호명은 "스타벅스" 단독 — 지점명이 따로 없고
    # 주소로만 철산역점임을 알 수 있음, 2026-09-21 확인)
    starbucks_case = None
    for sid, st in cur.items():
        if st.name == "스타벅스" and st.road and "철산로 15" in st.road:
            res = match_store(st, i1200_by_name, args.radius_m)
            starbucks_case = {
                "상가업소번호": sid, "상호명": st.name, "도로명주소": st.road,
                "신규여부": sid in final_opened_ids,
                "lon": st.lon, "lat": st.lat,
                "매칭": None if res is None else {
                    "i1200_상호명": res[0]["name"], "허가일": res[0]["prms_dt"],
                    "폐업일": res[0]["clsbiz_dt"], "거리m": round(res[1], 1),
                    "관리번호": res[0]["lcns_no"],
                },
            }
            break

    report = {
        "note_추측표시": "이 파일의 비율/건수는 정규화상호명+좌표50m 매칭 기반 추정이며, "
                       "I1200 오픈API 의 LOCP_ADDR 이 시군구수준이라 도로명주소 매칭(과제 키 ①③)은 "
                       "불가능했다(조사 결과, 추측 아님). 매칭 자체(어느 상가가 어느 인허가와 같은 "
                       "가게인지)는 이름+좌표 근접이라는 발견적 방법이므로 개별 건은 오매칭 가능성이 있다.",
        "radius_m": args.radius_m,
        "quarter": {"current": args.current_quarter, "previous": args.previous_quarter},
        "final_opened_total": len(final_opened_ids),
        "final_closed_total": len(final_closed_ids),
        "food_large_code": food_code,
        "opened_food": {
            "count": len(opened_food_ids),
            "ratio_of_all_opened": round(len(opened_food_ids) / max(1, len(final_opened_ids)), 4),
            "matched_count": len(opened_matched),
            "matched_ratio": round(len(opened_matched) / max(1, len(opened_food_ids)), 4),
            "matched_pre_20250630_prms_dt_count": opened_pre_threshold,
            "matched_pre_20250630_prms_dt_ratio": round(opened_pre_threshold / max(1, len(opened_matched)), 4),
            "prms_year_distribution": dict(opened_year_dist),
        },
        "closed_food": {
            "count": len(closed_food_ids),
            "ratio_of_all_closed": round(len(closed_food_ids) / max(1, len(final_closed_ids)), 4),
            "matched_count": len(closed_matched),
            "matched_ratio": round(len(closed_matched) / max(1, len(closed_food_ids)), 4),
            "matched_still_operating_count": closed_still_open,
            "matched_still_operating_ratio": round(closed_still_open / max(1, len(closed_matched)), 4),
            "clsbiz_distribution": dict(closed_clsbiz_dist),
        },
        "i1200_ground_truth_window_20250701_20260630": {
            "i1200_rows_with_coord_used": i1200_all,
            "licensed_in_window": i1200_licensed_in_window,
            "closed_in_window": i1200_closed_in_window,
            "vs_sangga_opened_food": len(opened_food_ids),
            "vs_sangga_closed_food": len(closed_food_ids),
        },
        "starbucks_cheolsan_case": starbucks_case,
        "i1200_fetch_status": {
            "rows_used": i1200_total,
            "note": "i1200_raw.ndjson 이 fetch_i1200.py 진행 상태에 따라 부분본일 수 있음 — "
                    "progress.json 의 rows_written/total_count 로 완결 여부 확인",
        },
    }

    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    map_path = out_dir / "store_license_map.ndjson"
    with open(map_path, "w", encoding="utf-8") as f:
        for sid, st, c, d in opened_matched:
            f.write(json.dumps({
                "상가업소번호": sid, "구분": "opened",
                "허가일": c["prms_dt"], "폐업일": c["clsbiz_dt"],
                "영업상태": "영업중" if not c["clsbiz_dt"] else "폐업",
                "인허가관리번호": c["lcns_no"], "거리m": round(d, 1),
            }, ensure_ascii=False) + "\n")
        for sid, st, c, d in closed_matched:
            f.write(json.dumps({
                "상가업소번호": sid, "구분": "closed",
                "허가일": c["prms_dt"], "폐업일": c["clsbiz_dt"],
                "영업상태": "영업중" if not c["clsbiz_dt"] else "폐업",
                "인허가관리번호": c["lcns_no"], "거리m": round(d, 1),
            }, ensure_ascii=False) + "\n")

    print(f"[build-license] report.json / store_license_map.ndjson 저장: {out_dir}")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
