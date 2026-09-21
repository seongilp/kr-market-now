"""분기 스냅샷 사이에서 "같은 가게"를 잇는 매칭 로직.

배경(왜 이 모듈이 필요한가): 소진공 상가(상권)정보는 점포를 상가업소번호로
식별한다. 원칙적으로 같은 점포는 분기마다 같은 번호를 유지해야 하지만,
2026년 6월(202606) 회차처럼 원본이 다수 점포의 상가업소번호를 새로
부여하는 경우가 실제로 있었다 — 검증 결과(2026-09-21) 202603->202606
구간에서만 신규 344,445 / 소멸 297,279 로 다른 분기 구간(대략
7~14만 건)의 2~4배였고, 신규 쪽 중 다수가 (정규화 상호명, 도로명주소,
층, 호)로 202603 스냅샷에서 그대로 찾아졌다(스타벅스 철산역 등 확인됨).
번호만으로 diff 하면 이런 "번호만 바뀐 같은 가게"가 소멸+신규로 이중
계산된다.

그래서 신규/소멸 판정은 두 단계로 한다:
  1차: 상가업소번호 매칭 (기존 로직 — 두 스냅샷의 id 교집합은 "계속 영업 중").
  2차: 1차에서 짝을 못 찾은 것들끼리 (정규화 상호명, 도로명주소, 층, 호)
       키로 1:1 매칭. 매칭된 쌍은 "같은 가게, 번호만 바뀜"으로 보고
       신규·소멸 양쪽에서 제외한다.

층/호까지 키에 포함하는 이유: 같은 건물(같은 도로명주소)에 여러 점포가
있는 프랜차이즈·상가 건물에서 "상호명+주소"만 쓰면 다른 층/호의 별개
점포를 같은 가게로 잘못 묶을 위험이 있다. 층/호를 더하면 이 위험이
크게 줄어든다(그래도 층/호 표기 자체가 비어있거나 표준화가 안 된
소수 사례는 여전히 모호할 수 있음 — 호출부에서 `ambiguous_groups` 로
그 규모를 셀 수 있다).

이 모듈은 build-data.py / build-insights.py / build-tiles.py 세 스크립트가
모두 import 해서 같은 규칙을 쓴다.
"""

from __future__ import annotations

from collections import defaultdict

from normalize import brand_is_noise, normalize_brand


def match_key(name: str, road: str, floor: str, ho: str) -> tuple[str, str, str, str] | None:
    """(정규화 상호명, 도로명주소, 층, 호) 매칭 키를 만든다.

    도로명주소가 없거나(주소 없는 행은 자리 특정이 안 됨), 정규화 상호명이
    브랜드 노이즈(상호없음/미정 등)거나 너무 짧으면 키를 만들지 않는다
    (`None`) — 과매칭 방지가 최우선이므로 애매하면 매칭하지 않는 쪽을
    택한다.
    """
    if not road:
        return None
    nb = normalize_brand(name)
    if brand_is_noise(nb):
        return None
    return (nb, road, floor or "", ho or "")


def pair_ids_by_key(
    prev_key_of: dict[str, tuple[str, str, str, str]],
    cur_key_of: dict[str, tuple[str, str, str, str]],
):
    """이미 계산된 매칭 키(`match_key()` 결과, None 제외)로 두 집합의 id를 1:1로 잇는다.

    `find_renumbered_pairs` 의 하위 로직 — build-tiles.py 처럼 여러 분기에
    걸쳐 키를 미리 한 번만 계산해두고 재사용하고 싶을 때 이 함수를 직접
    호출한다(키를 두 번 계산하지 않도록).

    같은 키에 후보가 여럿이면(드묾) 정렬 후 1:1로만 잇고 나머지는 버린다
    (과매칭 방지, 입력 순서 비의존).

    반환: (matched_prev_ids: set[str], matched_cur_ids: set[str],
           pairs: list[tuple[str, str]], ambiguous_groups: int)
    """
    prev_by_key: dict[tuple, list[str]] = defaultdict(list)
    for sid, k in prev_key_of.items():
        prev_by_key[k].append(sid)

    cur_by_key: dict[tuple, list[str]] = defaultdict(list)
    for sid, k in cur_key_of.items():
        cur_by_key[k].append(sid)

    matched_prev: set[str] = set()
    matched_cur: set[str] = set()
    pairs: list[tuple[str, str]] = []
    ambiguous_groups = 0

    for k in sorted(set(prev_by_key) & set(cur_by_key)):
        plist = sorted(prev_by_key[k])
        clist = sorted(cur_by_key[k])
        if len(plist) > 1 or len(clist) > 1:
            ambiguous_groups += 1
        for p, c in zip(plist, clist):
            matched_prev.add(p)
            matched_cur.add(c)
            pairs.append((p, c))

    return matched_prev, matched_cur, pairs, ambiguous_groups


def find_renumbered_pairs(
    prev_only: dict[str, tuple[str, str, str, str]],
    cur_only: dict[str, tuple[str, str, str, str]],
):
    """1차(번호) 매칭에서 짝을 못 찾은 id들 사이에서 번호 재부여 쌍을 찾는다.

    prev_only / cur_only: {id: (name, road, floor, ho)} — 각각 "상대 스냅샷에
    없는" id만 담아서 넘긴다(전체 레코드를 넘기지 않는다 — 메모리/속도).

    반환: pair_ids_by_key 와 동일 — (matched_prev_ids, matched_cur_ids, pairs,
    ambiguous_groups).
    """
    prev_key_of = {
        sid: k
        for sid, (name, road, floor, ho) in prev_only.items()
        if (k := match_key(name, road, floor, ho)) is not None
    }
    cur_key_of = {
        sid: k
        for sid, (name, road, floor, ho) in cur_only.items()
        if (k := match_key(name, road, floor, ho)) is not None
    }
    return pair_ids_by_key(prev_key_of, cur_key_of)


def resolve_opened_closed(
    cur_ids: set[str],
    prev_ids: set[str],
    cur_key_of: dict[str, tuple[str, str, str, str]],
    prev_key_of: dict[str, tuple[str, str, str, str]],
):
    """1차(번호)+2차((상호,주소,층,호)) 매칭을 모두 적용해 최종 opened/closed id
    집합을 만든다.

    cur_key_of / prev_key_of: 각 분기 "전체" id -> (name, road, floor, ho).
    2차 키 조회에 필요한 것만 넘기면 되므로, 호출부는 1차에서 걸러지지
    않은(=상대 분기에 없는) id에 대해서만 조회 딕셔너리를 만들어 넘겨도 된다
    (아래 raw_opened/raw_closed 만 커버하면 충분).

    반환: (opened_ids, closed_ids, renumbered_pairs, ambiguous_groups)
    opened_ids/closed_ids 는 번호 재부여로 판정된 쌍이 제외된 최종 집합.
    """
    raw_opened = cur_ids - prev_ids
    raw_closed = prev_ids - cur_ids

    prev_only = {sid: prev_key_of[sid] for sid in raw_closed}
    cur_only = {sid: cur_key_of[sid] for sid in raw_opened}

    matched_prev, matched_cur, pairs, ambiguous_groups = find_renumbered_pairs(prev_only, cur_only)

    opened_ids = raw_opened - matched_cur
    closed_ids = raw_closed - matched_prev

    return opened_ids, closed_ids, pairs, ambiguous_groups
