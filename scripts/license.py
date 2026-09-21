"""store_license_map.ndjson 공용 로더 — build-data.py/build-insights.py/build-tiles.py
가 함께 쓴다.

배경: scripts/build-license.py 가 소진공 상가업소번호 <-> 지방행정인허가데이터를
조인해 scratchpad 에 store_license_map.ndjson 을 만든다(허가일/폐업일/영업상태/
매칭방식). 이 모듈은 그 파일을 읽어, "소진공 opened(신규 추정)인데 실제로는
예전부터 영업 중이던 곳(등록 지연)"과 "소진공 closed(소멸 추정)인데 인허가상
아직 영업 중인 곳"을 판정하는 공용 규칙을 제공한다.

판정 신뢰도: build-license.py 의 매칭 3단계 중 ①(정규화상호명+도로명주소 정확일치),
①b(같은 도로명주소+상호명 접두어관계), ②(정규화상호명+좌표50m)만 재분류(k 값을
바꾸는 것)에 쓴다. ③(도로명주소 단독, 그 주소에 양쪽 다 미매칭 1개씩일 때만 묶는
근사)은 신뢰도가 낮아 재분류에는 안 쓰고, 허가일/폐업일 "표시"(a/c 속성)에만 쓴다
— 과제 지시.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

# 재분류(stale/unverified 판정)에 쓸 수 있는 매칭방식만. ③(tier3_road_only)은 제외.
RECLASSIFY_TIERS = frozenset({"tier1_name+road", "tier1b_road+nameprefix", "tier2_name+coord"})

# opened 인데 허가일이 이보다 이르면 "예전부터 영업"(stale, k=3)으로 본다.
# 소진공 비교 기준 분기가 1년 전(202506)이므로 그 시작일을 기준으로 삼는다.
STALE_CUTOFF = 20250701

# 1단계 보고서(scratchpad/license-join/store_license_map.ndjson)의 기본 경로.
# 스크래치는 세션마다 바뀌므로, 각 빌드 스크립트가 --license-map 인자로 덮어쓸 수 있다.
DEFAULT_LICENSE_MAP_PATH = Path(
    "/private/tmp/claude-501/-Users-zihado-work-playground-datalab/"
    "09a42e90-1062-4277-988d-5bcc3294fb1f/scratchpad/license-join/store_license_map.ndjson"
)


class LicenseInfo(NamedTuple):
    kind: str  # "opened" | "closed"
    license_date: int | None  # YYYYMMDD
    close_date: int | None  # YYYYMMDD
    status: str | None
    tier: str | None

    @property
    def reclassify_eligible(self) -> bool:
        return self.tier in RECLASSIFY_TIERS


def load_license_map(path: Path = DEFAULT_LICENSE_MAP_PATH) -> dict[str, LicenseInfo]:
    """상가업소번호 -> LicenseInfo. 파일이 없으면 빈 dict(호출부는 이 경우 기존 로직
    그대로 동작해야 함 — 이 모듈 없이도 빌드가 깨지지 않게)."""
    out: dict[str, LicenseInfo] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            out[r["상가업소번호"]] = LicenseInfo(
                kind=r.get("구분"),
                license_date=r.get("허가일"),
                close_date=r.get("폐업일"),
                status=r.get("영업상태"),
                tier=r.get("매칭방식"),
            )
    return out


def quarter_bucket(date_int: int) -> int:
    """YYYYMMDD -> 1~4. 2025-07~10=1, 11~12=2, 2026-01~03=3, 04~06=4.
    범위 밖(2025-06 이전/2026-07 이후)은 가까운 쪽 끝(1 또는 4)으로 clamp."""
    if date_int <= 20251031:
        return 1
    if date_int <= 20251231:
        return 2
    if date_int <= 20260331:
        return 3
    return 4


class Reclass(NamedTuple):
    """재분류 결과. new_k 가 None 이면 원래 k(opened=1/closed=0) 유지, 아니면 그 k로
    바꾸고 원래 목록(opened/closed)에서는 제외해야 한다. q_override 는 None 이면
    기존 로직(분기 스냅샷 등장 시점)의 q 를 그대로 쓰고, 정수면 그 값으로 덮어쓴다.
    a/c 는 있으면 타일 속성에 얹을 허가일/폐업일(표시용, tier3 매칭도 포함)."""
    new_k: int | None
    q_override: int | None
    a: int | None
    c: int | None


def classify_opened(sid: str, license_map: dict[str, LicenseInfo]) -> Reclass:
    info = license_map.get(sid)
    if info is None or info.kind != "opened":
        return Reclass(None, None, None, None)
    if not info.reclassify_eligible:
        # ③(주소단독) 매칭 — 재분류엔 안 쓰지만 날짜는 표시.
        return Reclass(None, None, info.license_date, info.close_date)
    if info.license_date is not None and info.license_date < STALE_CUTOFF:
        return Reclass(3, None, info.license_date, info.close_date)
    q_override = quarter_bucket(info.license_date) if info.license_date is not None else None
    return Reclass(None, q_override, info.license_date, info.close_date)


def classify_closed(sid: str, license_map: dict[str, LicenseInfo]) -> Reclass:
    info = license_map.get(sid)
    if info is None or info.kind != "closed":
        return Reclass(None, None, None, None)
    if not info.reclassify_eligible:
        return Reclass(None, None, info.license_date, info.close_date)
    if info.close_date is None:
        return Reclass(4, None, info.license_date, info.close_date)
    q_override = quarter_bucket(info.close_date)
    return Reclass(None, q_override, info.license_date, info.close_date)
