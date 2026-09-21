#!/usr/bin/env python3
"""소진공 상가(상권)정보 식품접객업 계열 점포 <-> 지방행정인허가데이터 조인.

배경: 소진공 상가정보는 원본에 폐업 정보가 없어 opened/closed 를 분기
스냅샷 비교로 "추정"한다(scripts/build-data.py, scripts/match.py). 그런데
지방행정 인허가데이터는 인허가일자·폐업일자가 명시돼 있어 실제 개폐업
시점을 알 수 있다 — 소진공 등록이 늦게 반영되는 경우(예: 스타벅스 철산역점,
인허가일 2019-10-22 인데 소진공 202603 회차까지 등장 안 함) "신규"로
오판될 수 있고, 반대로 실제로는 폐업했는데 소진공에 아직 남아있어 "소멸"
판정이 늦어질 수도 있다. 이 스크립트는 그 격차를 정량화한다.

데이터 소스 조사 결과(2026-09-21):
  - localdata.go.kr(www 도메인)은 이 실행 환경에서 curl/헤드리스 브라우저
    모두 TLS 핸드셰이크 전에 연결 타임아웃 — 접근 불가.
  - **찾은 우회로**: data.go.kr 의 "행정안전부_식품_XXX" 파일데이터 상세
    페이지("제공형태: 기관자체에서 다운로드") 가 실제로는
    `https://file.localdata.go.kr/file/<slug>/info` 를 가리키는데, 이
    서브도메인은 (www.localdata.go.kr 과 달리) 이 환경에서 접속된다
    (Referer 헤더 필요 — 없으면 /error.html 로 302). 그 페이지의
    "전체 다운로드" 버튼이 부르는 `GET /file/download-all` 이 슬러그와
    무관하게 **지방행정인허가데이터 전체(모든 업종, 1,086개 CSV)를
    담은 단일 zip("인허가정보.zip", 약 925MB)** 을 반환한다 — 로그인
    불필요, curl 만으로 수 초~수십 초 안에 전량 확보(scripts/../scratchpad
    localdata/dl_localdata_all.sh 참고). 식약처 I1200 오픈API(하루
    2,000회 제한, 좌표는 있지만 주소가 시군구수준까지만 나옴)보다 압도적으로
    빠르고 데이터도 더 좋아 이 경로로 전환했다 — fetch_i1200*.py 는 중단,
    받아둔 부분 데이터만 교차검증용으로 남겼다.
  - **좌표계**: CSV의 "좌표정보(X)"/"좌표정보(Y)" 는 TM(EPSG:5174, 중부원점
    Bessel1841)이다. 실측 검증: 스타벅스철산역점 좌표
    (188226.3396, 441595.6398) 를 EPSG:5174 -> EPSG:4326 로 pyproj 변환하면
    (126.867684, 37.476469) — 과제에서 준 참값(126.8677, 37.4765)과
    10m 이내 일치. EPSG:5181/2097/5186 등 다른 후보는 이보다 어긋난다.
  - **주소**: "도로명주소" 컬럼에 건물명/층/호 정보가 콤마로 이어 붙어있다
    (예: "경기도 광명시 철산로 15, 웅진빌딩 1층 일부호 (철산동)"). 첫
    콤마 앞부분("경기도 광명시 철산로 15")이 소진공 "도로명주소" 컬럼
    형식과 정확히 같아 road_prefix 로 쓸 수 있다(실측 확인됨).
  - 인허가일자 2019-10-22 — 과제에서 준 값과 정확히 일치(스타벅스철산역점,
    식품_휴게음식점.csv).

매칭 3단계(과제 지시 순서, 각 단계는 이전 단계에서 못 찾은 것만 시도):
  ① 정규화 상호명 + road_prefix 정확히 일치
  ② 정규화 상호명 + 좌표 반경 --radius-m(기본 50m) 이내 최근접
  ③ road_prefix 만 일치(상호명 무시) + 그 road_prefix 안에서 소진공쪽
     미매칭 1개 : 인허가쪽 미매칭 1개로 1:1인 경우만(모호하면 skip) —
     "층·호 단독" 매칭의 근사치(자유서식 층/호 텍스트를 안정적으로 파싱하기
     어려워 도로명주소 전체를 키로 씀 — 과제가 요청한 것보다 다소 느슨한
     근사이며 그렇게 표시한다, 추측).

사용법:
    python3 scripts/build-license.py \
        --current-zip <202606 zip> --current-quarter 202606 \
        --previous-zip <202506 zip> --previous-quarter 202506 \
        --localdata-zip <scratchpad>/localdata/인허가정보_전체.zip \
        --out-dir <scratchpad>/license-join \
        [--radius-m 50] [--i1200-ndjson <scratchpad>/localdata/i1200_raw.ndjson]

출력(모두 scratchpad, 리포에는 커밋 안 함):
  - <out-dir>/store_license_map.ndjson : 상가업소번호 -> {허가일, 폐업일,
    영업상태, 인허가관리번호, 매칭방식, 거리m(있으면)}
  - <out-dir>/report.json : 정량화 결과
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

try:
    from pyproj import Transformer
except ImportError:  # pragma: no cover
    Transformer = None

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

# 인허가정보.zip 안에서 "식품접객업 계열"로 볼 CSV 목록(식품 폴더 하위).
# 즉석판매제조가공업/집단급식소식품판매업은 손님이 매장에서 먹는 "접객업"이라기보다
# 제조/판매업에 가깝지만, 카페·베이커리 일부가 이 코드로 등록되는 경우가 있어
# 매칭 후보 풀에는 포함하고(놓치는 것보다 낫다는 판단), 정량화 보고에서는 이
# 사실을 명시한다.
FOOD_CSV_MEMBERS = [
    "식품/식품_일반음식점.csv",
    "식품/식품_휴게음식점.csv",
    "식품/식품_제과점영업.csv",
    "식품/식품_단란주점영업.csv",
    "식품/식품_유흥주점영업.csv",
    "식품/식품_집단급식소.csv",
    "식품/식품_위탁급식영업.csv",
    "식품/식품_관광식당.csv",
    "식품/식품_즉석판매제조가공업.csv",
    "식품/식품_집단급식소식품판매업.csv",
]

TM_EPSG = "EPSG:5174"  # 중부원점(Bessel1841) — 스타벅스철산역점 좌표로 검증됨


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
        self.road = row[IDX["도로명주소"]].strip()
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


LOCALDATA_COLS = [
    "개방자치단체코드", "관리번호", "인허가일자", "영업상태명", "폐업일자",
    "소재지면적", "소재지우편번호", "도로명우편번호", "사업장명", "업태구분명",
    "데이터갱신구분", "건물소유구분명", "공장사무직직원수", "공장생산직직원수",
    "공장판매직직원수", "급수시설구분명", "남성종사자수", "다중이용업소여부",
    "데이터갱신시점", "도로명주소", "등급구분명", "보증액", "본사직원수",
    "상세영업상태명", "상세영업상태코드", "시설총규모", "여성종사자수",
    "영업상태코드", "영업장주변구분명", "월세액", "위생업태명", "전통업소주된음식",
    "전통업소지정번호", "전화번호", "좌표정보(X)", "좌표정보(Y)", "지번주소",
    "홈페이지", "최종수정시점",
]
LIDX = {n: i for i, n in enumerate(LOCALDATA_COLS)}


def road_prefix(road_addr: str) -> str:
    """"경기도 광명시 철산로 15, 웅진빌딩 1층 일부호 (철산동)" -> "경기도 광명시 철산로 15"."""
    if not road_addr:
        return ""
    return road_addr.split(",", 1)[0].strip()


def load_localdata_food(zip_path: Path, members: list[str] = FOOD_CSV_MEMBERS):
    """지방행정인허가데이터(localdata.go.kr) 식품접객업 계열 CSV 들을 적재.

    반환: (records: list[dict], per_file_stats: dict[str, dict])
    각 record: mgmt_no, name, road, road_pref, license_date(YYYYMMDD int or
    None), close_date(YYYYMMDD int or None), status_name, status_detail,
    lon, lat(WGS84, 변환 실패/범위밖이면 None), category(파일명에서 추출),
    last_update(YYYYMMDD int or None)
    """
    if Transformer is None:
        raise SystemExit("[build-license] pyproj 가 필요합니다: pip install pyproj")
    transformer = Transformer.from_crs(TM_EPSG, "EPSG:4326", always_xy=True)

    records: list[dict] = []
    per_file_stats: dict[str, dict] = {}

    with zipfile.ZipFile(zip_path) as z:
        available = set(z.namelist())
        for member in members:
            if member not in available:
                print(f"[build-license][경고] {member} zip 안에 없음 — 건너뜀", file=sys.stderr)
                continue
            category = member.rsplit("/", 1)[-1].replace("식품_", "").replace(".csv", "")
            rows = 0
            coord_ok = 0
            coord_fail = 0
            max_update = None
            with z.open(member) as raw:
                tf = io.TextIOWrapper(raw, encoding="cp949", errors="replace", newline="")
                reader = csv.reader(tf)
                header = next(reader)
                if len(header) != len(LOCALDATA_COLS):
                    print(f"[build-license][경고] {member} 헤더 컬럼 수 {len(header)} != {len(LOCALDATA_COLS)}",
                          file=sys.stderr)
                for row in reader:
                    if len(row) != len(LOCALDATA_COLS):
                        continue
                    rows += 1
                    name = row[LIDX["사업장명"]].strip()
                    if not name:
                        continue
                    road = row[LIDX["도로명주소"]].strip()
                    x_raw = row[LIDX["좌표정보(X)"]].strip()
                    y_raw = row[LIDX["좌표정보(Y)"]].strip()
                    lon = lat = None
                    if x_raw and y_raw:
                        try:
                            x, y = float(x_raw), float(y_raw)
                            lon, lat = transformer.transform(x, y)
                            if not (124.0 <= lon <= 132.5 and 32.5 <= lat <= 39.5):
                                lon = lat = None
                        except (ValueError, TypeError):
                            lon = lat = None
                    if lon is not None:
                        coord_ok += 1
                    else:
                        coord_fail += 1

                    lic = row[LIDX["인허가일자"]].replace("-", "")
                    lic_i = int(lic) if lic.isdigit() and len(lic) == 8 else None
                    cls = row[LIDX["폐업일자"]].replace("-", "")
                    cls_i = int(cls) if cls.isdigit() and len(cls) == 8 else None
                    upd = row[LIDX["최종수정시점"]][:10].replace("-", "")
                    upd_i = int(upd) if upd.isdigit() and len(upd) == 8 else None
                    if upd_i and (max_update is None or upd_i > max_update):
                        max_update = upd_i

                    records.append({
                        "mgmt_no": row[LIDX["관리번호"]],
                        "name": name,
                        "norm": normalize_brand(name),
                        "road": road,
                        "road_pref": road_prefix(road),
                        "license_date": lic_i,
                        "close_date": cls_i,
                        "status_name": row[LIDX["영업상태명"]],
                        "status_detail": row[LIDX["상세영업상태명"]],
                        "lon": lon, "lat": lat,
                        "category": category,
                        "last_update": upd_i,
                    })
            per_file_stats[category] = {
                "rows": rows, "coord_ok": coord_ok, "coord_fail": coord_fail,
                "max_last_update": max_update,
            }
    return records, per_file_stats


def build_indices(records: list[dict]):
    by_name_road: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_name: dict[str, list[dict]] = defaultdict(list)
    by_road: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        if brand_is_noise(r["norm"]):
            continue
        if r["road_pref"]:
            by_name_road[(r["norm"], r["road_pref"])].append(r)
            by_road[r["road_pref"]].append(r)
        by_name[r["norm"]].append(r)
    return by_name_road, by_name, by_road


def match_tier1(store: Store, by_name_road):
    if not store.road:
        return None
    norm = normalize_brand(store.name)
    if brand_is_noise(norm):
        return None
    cands = by_name_road.get((norm, store.road))
    if not cands:
        return None
    # 여러 개면(같은 상호+주소가 여러 인허가 행 — 드묾) 가장 최근 허가일자를 고른다.
    best = max(cands, key=lambda r: r["license_date"] or 0)
    return best


def match_tier1b(store: Store, by_road):
    """도로명주소 일치 + 상호명 "포함"관계(접두어) — tier1 의 완화판.

    실측 사례: 소진공은 브랜드명만("스타벅스"), 인허가데이터는 지점명까지
    ("스타벅스철산역점") 적는 경우가 흔하다. normalize_brand() 는 "...점"
    패턴을 한 번만 벗기므로 "철산역"처럼 지점을 가리키는 중간 토큰까지는
    못 없앤다 — 그래서 정확일치(tier1)로는 이런 쌍을 못 잡는다. 같은
    건물(도로명주소 정확일치)이라는 강한 제약이 있을 때만, 정규화 상호명이
    서로 접두어 관계(둘 중 하나가 다른 하나로 시작)면 같은 가게로 본다.
    브랜드명이 통째로 다른 가게로 바뀌는(간판 교체) 경우는 이 조건을
    만족 못 해 여기서 걸러지지 않는다(그런 경우는 안 잡는 게 맞음)."""
    if not store.road:
        return None
    norm = normalize_brand(store.name)
    if brand_is_noise(norm) or len(norm) < 2:
        return None
    cands = [c for c in by_road.get(store.road, [])
             if not brand_is_noise(c["norm"]) and (c["norm"].startswith(norm) or norm.startswith(c["norm"]))]
    if not cands:
        return None
    if len(cands) > 1:
        # 모호하면 접두어가 가장 길게 겹치는(=더 구체적으로 같은) 것을 우선.
        cands.sort(key=lambda c: -min(len(c["norm"]), len(norm)))
        if len(cands[0]["norm"]) == len(cands[1]["norm"]):
            return None  # 진짜 모호 — 포기
    return cands[0]


def match_tier2(store: Store, by_name, radius_m: float):
    if store.lon is None or store.lat is None:
        return None
    norm = normalize_brand(store.name)
    if brand_is_noise(norm):
        return None
    cands = by_name.get(norm)
    if not cands:
        return None
    best = None
    best_d = None
    for c in cands:
        if c["lon"] is None:
            continue
        d = haversine_m(store.lon, store.lat, c["lon"], c["lat"])
        if d <= radius_m and (best_d is None or d < best_d):
            best_d = d
            best = c
    if best is None:
        return None
    return best, best_d


def match_tier3(store_ids_unmatched, snapshot, by_road, used_mgmt_nos: set[str]):
    """road_prefix 단독 매칭(상호명 무시) — 그 주소에 소진공쪽 미매칭 1개,
    인허가쪽(아직 tier1/2 에서 안 쓰인) 후보가 정확히 1개일 때만 1:1로 묶는다."""
    by_road_store: dict[str, list[str]] = defaultdict(list)
    for sid in store_ids_unmatched:
        road = snapshot[sid].road
        if road:
            by_road_store[road].append(sid)

    results: dict[str, dict] = {}
    for road, sids in by_road_store.items():
        if len(sids) != 1:
            continue  # 모호(같은 주소에 미매칭 소진공 점포 2개 이상) — 건너뜀
        cands = [c for c in by_road.get(road, []) if c["mgmt_no"] not in used_mgmt_nos]
        if len(cands) != 1:
            continue  # 후보 0개 또는 2개 이상 — 건너뜀(과매칭 방지)
        results[sids[0]] = cands[0]
    return results


def parse_ymd(v):
    return v  # 이미 int(YYYYMMDD) or None


def bucket_year(lic: int | None) -> str:
    if lic is None:
        return "unknown"
    y = lic // 10000
    if y < 2020:
        return "2019이전"
    if 2020 <= y <= 2024:
        return "2020~2024"
    if lic < 20250701:
        return "2025H1"
    return "2025H2~2026"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--current-zip", required=True, type=Path)
    ap.add_argument("--current-quarter", required=True)
    ap.add_argument("--previous-zip", required=True, type=Path)
    ap.add_argument("--previous-quarter", required=True)
    ap.add_argument("--localdata-zip", required=True, type=Path)
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

    print(f"[build-license] 인허가데이터 적재: {args.localdata_zip}")
    ld_records, per_file_stats = load_localdata_food(args.localdata_zip)
    print(f"  -> 인허가 레코드 {len(ld_records):,}건 (파일별 통계는 report.json 참고)")
    for cat, st in per_file_stats.items():
        print(f"     {cat}: rows={st['rows']:,} coord_ok={st['coord_ok']:,} "
              f"coord_fail={st['coord_fail']:,} max_last_update={st['max_last_update']}")

    by_name_road, by_name, by_road = build_indices(ld_records)

    def match_all(ids, snapshot):
        matched: dict[str, tuple[dict, str, float | None]] = {}
        used_mgmt = set()
        unmatched = []
        for sid in ids:
            st = snapshot[sid]
            r = match_tier1(st, by_name_road)
            if r is not None:
                matched[sid] = (r, "tier1_name+road", 0.0)
                used_mgmt.add(r["mgmt_no"])
                continue
            r1b = match_tier1b(st, by_road)
            if r1b is not None and r1b["mgmt_no"] not in used_mgmt:
                matched[sid] = (r1b, "tier1b_road+nameprefix", 0.0)
                used_mgmt.add(r1b["mgmt_no"])
                continue
            res2 = match_tier2(st, by_name, args.radius_m)
            if res2 is not None:
                r, d = res2
                matched[sid] = (r, "tier2_name+coord", d)
                used_mgmt.add(r["mgmt_no"])
                continue
            unmatched.append(sid)

        tier3 = match_tier3(unmatched, snapshot, by_road, used_mgmt)
        for sid, r in tier3.items():
            matched[sid] = (r, "tier3_road_only", None)
            used_mgmt.add(r["mgmt_no"])
            unmatched.remove(sid)

        return matched, unmatched

    print(f"[build-license] 3단계 매칭 (반경 {args.radius_m}m)...")
    opened_matched, opened_unmatched = match_all(opened_food_ids, cur)
    closed_matched, closed_unmatched = match_all(closed_food_ids, prev)

    tier_counts_opened = Counter(v[1] for v in opened_matched.values())
    tier_counts_closed = Counter(v[1] for v in closed_matched.values())
    print(f"  -> 신규 매칭 {len(opened_matched):,}/{len(opened_food_ids):,} "
          f"({len(opened_matched)/max(1,len(opened_food_ids))*100:.1f}%) 단계별={dict(tier_counts_opened)}")
    print(f"  -> 소멸 매칭 {len(closed_matched):,}/{len(closed_food_ids):,} "
          f"({len(closed_matched)/max(1,len(closed_food_ids))*100:.1f}%) 단계별={dict(tier_counts_closed)}")

    # ---- 정량화 ----
    LATE_REG_THRESHOLD = 20250630

    opened_pre_threshold = sum(1 for r, _t, _d in opened_matched.values()
                                if r["license_date"] is not None and r["license_date"] <= LATE_REG_THRESHOLD)
    opened_year_dist = Counter(bucket_year(r["license_date"]) for r, _t, _d in opened_matched.values())

    closed_still_open = sum(1 for r, _t, _d in closed_matched.values() if r["close_date"] is None)
    closed_clsbiz_dist = Counter()
    for r, _t, _d in closed_matched.values():
        cd = r["close_date"]
        if cd is None:
            closed_clsbiz_dist["영업중(폐업일 없음)"] += 1
        else:
            y = cd // 10000
            if y < 2020:
                closed_clsbiz_dist["2019이전"] += 1
            elif y <= 2024:
                closed_clsbiz_dist["2020~2024"] += 1
            elif cd < 20250701:
                closed_clsbiz_dist["2025H1"] += 1
            else:
                closed_clsbiz_dist["2025H2~2026"] += 1

    # 인허가데이터 자체 기준 2025-07~2026-06 허가/폐업 건수(전국, 식품접객업 전체)
    window_lo, window_hi = 20250701, 20260630
    ld_licensed_in_window = sum(1 for r in ld_records if r["license_date"] and window_lo <= r["license_date"] <= window_hi)
    ld_closed_in_window = sum(1 for r in ld_records if r["close_date"] and window_lo <= r["close_date"] <= window_hi)

    # 스타벅스 철산역 사례 추적
    starbucks_case = None
    for sid, st in cur.items():
        if st.name == "스타벅스" and st.road and "철산로 15" in st.road:
            hit = opened_matched.get(sid)
            starbucks_case = {
                "상가업소번호": sid, "상호명": st.name, "도로명주소": st.road,
                "신규여부(소진공 기준)": sid in final_opened_ids,
                "lon": st.lon, "lat": st.lat,
                "매칭": None if hit is None else {
                    "인허가_사업장명": hit[0]["name"], "허가일": hit[0]["license_date"],
                    "폐업일": hit[0]["close_date"], "매칭방식": hit[1],
                    "거리m": hit[2], "관리번호": hit[0]["mgmt_no"],
                    "인허가_도로명주소": hit[0]["road"],
                },
            }
            break

    report = {
        "note_추측표시": (
            "매칭은 ①정규화상호명+도로명주소(첫콤마전) 정확일치 ①b같은 도로명주소+상호명"
            "접두어관계(소진공 '스타벅스' vs 인허가 '스타벅스철산역점' 같이 지점명이 "
            "붙는 흔한 케이스 보정, 모호하면 포기) ②정규화상호명+좌표"
            f"{args.radius_m:.0f}m ③도로명주소 단독(그 주소에 양쪽 다 미매칭 1개씩일 때만) "
            "순서로 시도. ③은 과제가 요청한 '층/호 단독' 대신 '도로명주소(건물)단독'을 "
            "쓴 근사(자유서식 층/호 텍스트 파싱이 불안정해 완화함) — 표시된 추측. "
            "①b도 상호명이 통째로 다른(간판 교체) 경우는 못 잡으므로 그 자체가 근사/추측. "
            "그 외(①②③) 매칭은 결정론적 키 매칭이라 근접매칭(②) 반경 안에서의 개별 오매칭"
            "가능성 외에는 추측이 아님."
        ),
        "radius_m": args.radius_m,
        "quarter": {"current": args.current_quarter, "previous": args.previous_quarter},
        "final_opened_total": len(final_opened_ids),
        "final_closed_total": len(final_closed_ids),
        "food_large_code": food_code,
        "localdata_per_file_stats": per_file_stats,
        "opened_food": {
            "count": len(opened_food_ids),
            "ratio_of_all_opened": round(len(opened_food_ids) / max(1, len(final_opened_ids)), 4),
            "matched_count": len(opened_matched),
            "matched_ratio": round(len(opened_matched) / max(1, len(opened_food_ids)), 4),
            "matched_by_tier": dict(tier_counts_opened),
            "matched_pre_20250630_license_date_count": opened_pre_threshold,
            "matched_pre_20250630_license_date_ratio": round(opened_pre_threshold / max(1, len(opened_matched)), 4),
            "license_year_distribution": dict(opened_year_dist),
        },
        "closed_food": {
            "count": len(closed_food_ids),
            "ratio_of_all_closed": round(len(closed_food_ids) / max(1, len(final_closed_ids)), 4),
            "matched_count": len(closed_matched),
            "matched_ratio": round(len(closed_matched) / max(1, len(closed_food_ids)), 4),
            "matched_by_tier": dict(tier_counts_closed),
            "matched_still_operating_count": closed_still_open,
            "matched_still_operating_ratio": round(closed_still_open / max(1, len(closed_matched)), 4),
            "close_date_distribution": dict(closed_clsbiz_dist),
        },
        "localdata_ground_truth_window_20250701_20260630": {
            "localdata_food_rows_total": len(ld_records),
            "licensed_in_window": ld_licensed_in_window,
            "closed_in_window": ld_closed_in_window,
            "vs_sangga_opened_food": len(opened_food_ids),
            "vs_sangga_closed_food": len(closed_food_ids),
        },
        "starbucks_cheolsan_case": starbucks_case,
    }

    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    map_path = out_dir / "store_license_map.ndjson"
    with open(map_path, "w", encoding="utf-8") as f:
        for sid, (r, tier, d) in opened_matched.items():
            f.write(json.dumps({
                "상가업소번호": sid, "구분": "opened",
                "허가일": r["license_date"], "폐업일": r["close_date"],
                "영업상태": r["status_name"], "인허가관리번호": r["mgmt_no"],
                "매칭방식": tier, "거리m": d,
            }, ensure_ascii=False) + "\n")
        for sid, (r, tier, d) in closed_matched.items():
            f.write(json.dumps({
                "상가업소번호": sid, "구분": "closed",
                "허가일": r["license_date"], "폐업일": r["close_date"],
                "영업상태": r["status_name"], "인허가관리번호": r["mgmt_no"],
                "매칭방식": tier, "거리m": d,
            }, ensure_ascii=False) + "\n")

    print(f"[build-license] report.json / store_license_map.ndjson 저장: {out_dir}")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
