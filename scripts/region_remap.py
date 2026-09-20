"""202506 -> 202606 시군구/행정동 코드 개편 대응 헬퍼.

202606 분기부터 광주광역시+전라남도가 "전남광주통합특별시"(시도코드 12)로 통합되며
27개 시군구 코드가 전부 새로 부여됐다(이름은 그대로 — 목포시, 동구, 광산구 등).
별개로 인천 중구/동구/서구가 제물포구/영종구/서해구/검단구로, 경기 화성시가
화성시 4개 구로 분할되며 이번에는 시군구명 자체도 바뀌었다.

이 모듈은 `scripts/region-code-map.json` 의 정적 매핑(이름 1:1 대응 — sigunguRename)과,
분할된 경우(sigunguSplit)는 "옛 행정동명이 새 시군구 후보들 중 어디 소속인지"를
현재 분기 데이터에서 만든 행정동 인덱스로 찾아 해결한다.

분할 시군구 중 일부 행정동은 이번에 더 잘게 쪼개졌다(예: 인천 중구의 "운서동" ->
영종구의 "운서1동"/"운서2동"). 이런 경우 정확한 행정동 코드까지는 못 맞추더라도
"어느 시군구에 속하는지"는 접미사 숫자를 뗀 이름(stem)으로 맞출 수 있다 —
실제로 검증해보니 이 두 케이스(운서동, 아라동) 모두 stem 기준으로 후보가 단 하나뿐이라
모호함이 없다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_DONG_STEM_RE = re.compile(r"\d+(?:\.\d+)?(?=(?:동|리|읍|면)$)")


def dong_stem(name: str) -> str:
    """행정동명에서 분동 숫자만 뗀 대표 이름. '운서1동' -> '운서동', '송림3.5동' -> '송림동'."""
    return _DONG_STEM_RE.sub("", name)


def load_region_map(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class RegionRemapper:
    """이전 분기 행의 (시군구코드, 행정동명)을 현재 분기 기준 코드로 맞춘다."""

    def __init__(self, region_map: dict, cur_dong_by_sigungu: dict[str, dict[str, str]]):
        """cur_dong_by_sigungu: 현재 분기 기준 {시군구코드: {행정동명: 행정동코드}}."""
        self.rename: dict[str, str] = region_map.get("sigunguRename", {})
        self.split: dict[str, list[str]] = region_map.get("sigunguSplit", {})
        self.cur_dong_by_sigungu = cur_dong_by_sigungu
        self._stem_index_cache: dict[tuple[str, ...], dict[str, str]] = {}
        self.unresolved_sigungu = 0
        self.unresolved_dong = 0

    def _stem_index(self, candidates: tuple[str, ...]) -> dict[str, str]:
        if candidates not in self._stem_index_cache:
            idx: dict[str, str] = {}
            for code in candidates:
                for dname in self.cur_dong_by_sigungu.get(code, {}):
                    idx.setdefault(dong_stem(dname), code)
            self._stem_index_cache[candidates] = idx
        return self._stem_index_cache[candidates]

    def resolve_sigungu(self, sigungu_code: str, dong_name: str) -> str:
        if sigungu_code in self.rename:
            return self.rename[sigungu_code]
        if sigungu_code in self.split:
            candidates = tuple(self.split[sigungu_code])
            if len(candidates) == 1:
                return candidates[0]
            for code in candidates:
                if dong_name in self.cur_dong_by_sigungu.get(code, {}):
                    return code
            code = self._stem_index(candidates).get(dong_stem(dong_name))
            if code:
                return code
            self.unresolved_sigungu += 1
            return candidates[0]  # 최선의 추정치(그래도 시군구 대분류는 맞음)
        return sigungu_code

    def resolve_dong_code(self, new_sigungu_code: str, dong_name: str, fallback: str) -> str:
        dongs = self.cur_dong_by_sigungu.get(new_sigungu_code, {})
        if dong_name in dongs:
            return dongs[dong_name]
        stem = dong_stem(dong_name)
        for dname, dcode in dongs.items():
            if dong_stem(dname) == stem:
                return dcode
        self.unresolved_dong += 1
        return fallback

    def is_affected(self, sigungu_code: str) -> bool:
        return sigungu_code in self.rename or sigungu_code in self.split


def build_cur_dong_index(dong_code_to_info: dict[str, tuple[str, str]]) -> dict[str, dict[str, str]]:
    """dong_code_to_info: {행정동코드: (시군구코드, 행정동명)} -> {시군구코드: {행정동명: 행정동코드}}."""
    idx: dict[str, dict[str, str]] = {}
    for dong_code, (sigungu_code, dong_name) in dong_code_to_info.items():
        idx.setdefault(sigungu_code, {})[dong_name] = dong_code
    return idx
