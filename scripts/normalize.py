"""상호명 정규화 — 브랜드 집계(build-insights.py)와 점포 재부여번호 매칭
(scripts/match.py)이 공유하는 단일 정의.

두 용도 모두 "같은 상호명 표기를 같은 문자열로 모아야" 정확해지므로 규칙을
한 곳에 둔다:
- 브랜드 집계: "스타벅스 강남점"과 "스타벅스(강남점)"을 같은 브랜드로 묶는다.
- 재부여번호 매칭(match.py): 같은 가게가 분기 사이에 상가업소번호만 바뀐
  경우를 "정규화 상호명 + 주소" 키로 다시 잇는다. 상호명 표기가 흔들리면
  (공백/괄호 유무 등) 매칭이 깨지므로 반드시 같은 정규화를 거쳐야 한다.
"""

from __future__ import annotations

import re

_LEGAL_FORM_TOKENS = ("주식회사", "㈜", "(주)", "유한회사")
_BRANCH_SUFFIXES = ("직영점", "가맹점", "대리점", "본점", "지점")
_GENERIC_JEOM_RE = re.compile(r"^(.{2,}?)(?:\d*호)?점$")
_NON_ALNUM_RE = re.compile(r"[^0-9A-Za-z가-힣]")

# 브랜드 노이즈 제외 목록(정규화 후 문자열 기준)
BRAND_NOISE = {
    "상호없음", "미정", "없음", "해당없음", "무상호", "상호미상", "상호",
    "개인", "일반", "기타", "업소명없음", "상호명없음", "동일", "해당사항없음",
}


def normalize_brand(raw_name: str) -> str:
    """상호명에서 브랜드명을 뽑는다. 지점명 컬럼은 애초에 쓰지 않는다(호출부 책임).

    규칙(순서대로 적용):
    1. "주식회사"/"㈜"/"(주)"/"유한회사" 같은 법인격 표기 제거
    2. 괄호·공백·특수문자 전부 제거 (한글/영문/숫자만 남김)
    3. 흔한 지점 접미사(직영점/가맹점/대리점/본점/지점) 제거 — 남는 길이가
       2자 이상일 때만(짧아지는 게 더 위험하므로 보수적으로)
    4. 그래도 남은 "...점" 패턴(예: "강남점", "1호점")을 한 번 더 제거
       — 이 역시 남는 길이가 2자 이상일 때만

    이후 "정규화된 전체 문자열이 같은 것"만 같은 브랜드로 묶는다(접두어
    유사도로 묶지 않음 — 과잉 병합 방지).
    """
    s = raw_name.strip()
    for tok in _LEGAL_FORM_TOKENS:
        s = s.replace(tok, "")
    s = _NON_ALNUM_RE.sub("", s)
    if not s:
        return s

    for suf in _BRANCH_SUFFIXES:
        if s.endswith(suf) and len(s) - len(suf) >= 2:
            s = s[: -len(suf)]
            break
    else:
        m = _GENERIC_JEOM_RE.match(s)
        if m and len(m.group(1)) >= 2:
            s = m.group(1)

    return s


def brand_is_noise(name: str) -> bool:
    return len(name) < 2 or name in BRAND_NOISE
