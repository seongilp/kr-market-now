/**
 * 인사이트용 파생 데이터 타입. `scripts/build-insights.py` 가 생성한다.
 *
 * 모든 opened/closed/전환/브랜드 수치는 원본에 없는 파생값이다:
 * - opened/closed: 두 분기 스냅샷을 상가업소번호로 비교한 추정 —
 *   단 번호만 재부여된 점포(같은 가게)는 (정규화 상호명, 도로명주소, 층, 호)
 *   2차 매칭으로 걸러 opened/closed 양쪽에서 제외한다(`scripts/match.py`,
 *   2026-09-21 정정). brands[].stores/prevStores 는 이 보정과 무관하게
 *   원본 레코드 전체 개수라 영향받지 않지만, opened/closed 컬럼은 보정된
 *   값이다.
 * - 전환(transition): 사라진 가게와 새로 생긴 가게를 같은 주소(도로명주소+층+호)로 이어 붙인 추정.
 *   위 보정 이후에 계산하므로, 번호 재부여로 생긴 가짜 전환 쌍(사실은 같은
 *   가게)이 상당수 줄었다(2026-09-21 검증: 전국 매칭 쌍 147,638 -> 82,776).
 * - 브랜드: 상호명에서 지점명·기호를 떼고 정규화한 문자열 기준 — 프랜차이즈 공식 집계가 아니다.
 *   이 정규화 함수(`scripts/normalize.py`)는 opened/closed 재부여 매칭과
 *   공유한다.
 */

/** 업종 한 줄의 공통 집계 */
export interface UpjongStat {
  code: string;
  name: string;
  /** 최신 분기 점포 수 */
  stores: number;
  /** 이전 분기 점포 수 */
  prevStores: number;
  opened: number;
  closed: number;
  /** closed / prevStores — "1년 사이 사라진 비율" (prevStores 가 0이면 0) */
  closeRate: number;
  /** opened / prevStores */
  openRate: number;
}

/** 중분류. 대분류는 `data/upjong.json` 의 표에서 찾는다(`largeNameOf`) */
export type MiddleUpjongStat = UpjongStat;

export interface SmallUpjongStat extends UpjongStat {
  middleCode: string;
  middleName: string;
}

/** 소멸 → 신규 업종 전환 (중분류 기준) */
export interface Transition {
  fromCode: string;
  fromName: string;
  toCode: string;
  toName: string;
  count: number;
}

/** 주소로 이어 붙인 실제 사례 하나 */
export interface TransitionExample {
  road: string;
  dong: string;
  /** 사라진 가게 */
  fromName: string;
  fromUpjong: string;
  /** 그 자리에 생긴 가게 */
  toName: string;
  toUpjong: string;
  lat: number;
  lon: number;
}

export interface BrandStat {
  /** 정규화한 브랜드명(표시용) */
  name: string;
  /** 브랜드가 속한 업종 중분류 중 최빈값 */
  upjong: string;
  stores: number;
  prevStores: number;
  opened: number;
  closed: number;
}

/** data/insights/national.json */
export interface NationalInsights {
  current: string;
  previous: string;
  middle: MiddleUpjongStat[];
  small: SmallUpjongStat[];
  /** 전국 전환 상위 조합 */
  transitions: Transition[];
  /** 주소 매칭에 성공한 소멸→신규 쌍의 수(신뢰도 표시용) */
  transitionMatched: number;
  brands: BrandStat[];
  /** 번호 재부여 매칭(2차) 결과 요약 — data-types.ts 의 Meta.sanityChecks.renumberMatching 과 동일한 값 */
  renumberMatching?: {
    rawOpened: number;
    rawClosed: number;
    matchedPairs: number;
    ambiguousKeyGroups: number;
  };
  /** 간판 바뀜 추정 매칭(3차) 결과 요약 — data-types.ts 의 Meta.sanityChecks.renameMatching 과 동일한 값.
   * matchedPairs 는 opened/closed/transitions 에서 빠지고 renamed 로만 센 쌍의 수. */
  renameMatching?: {
    matchedPairs: number;
    excludedBothFloorHoEmpty: number;
    ambiguousKeyGroups: number;
  };
  /** 연도별(6월 기준) 업종 점포 수 추이. years 와 같은 길이의 배열.
   * 키는 업종 코드가 아니라 **업종명**이다(연도 사이 코드 재부여에 안전하도록). `yearlySeries()` 로 찾을 것 */
  yearly: {
    years: number[];
    middle: Record<string, number[]>;
    small: Record<string, number[]>;
  };
}

/** data/insights/region/{시군구코드}.json */
export interface RegionInsights {
  code: string;
  middle: MiddleUpjongStat[];
  /** 점포 수 상위 소분류 */
  small: SmallUpjongStat[];
  transitions: Transition[];
  transitionExamples: TransitionExample[];
  brands: BrandStat[];
}
