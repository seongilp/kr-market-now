/**
 * 상권나우 정적 데이터(JSON) 타입 정의.
 *
 * 이 타입들이 가리키는 JSON 파일은 `scripts/build-data.py` 가
 * `data/` 아래에 생성한다. 원본(소진공 상가(상권)정보)은 "영업 중인"
 * 점포만 수록하고 폐업 정보를 제공하지 않는다. 이 데이터셋의
 * `opened`/`closed`, `delta`, `turnoverRate` 는 모두 **두 분기 스냅샷을
 * 상가업소번호로 비교해서 만들어낸 파생값(추정치)** 이며, 원본 API가
 * 직접 제공하는 값이 아니다. 상가업소번호가 분기 사이에 재사용되거나
 * 시스템 정비로 바뀌는 경우가 있을 수 있어 완전히 정확한 개폐업 통계는
 * 아니라는 점에 유의할 것 — `Meta.sanityChecks.idIntersection` 을 통해
 * 이 가정이 얼마나 타당한지 확인할 수 있다.
 */

/** data/meta.json */
export interface Meta {
  /** 최신 분기(YYYYMM, 예: "202606" = 2026년 6월 말 기준 스냅샷) */
  current: string;
  /** 비교 기준이 된 이전 분기(YYYYMM). 목표는 1년 전이지만, 구하지 못하면
   * 확보 가능한 가장 가까운 과거 분기를 쓴다 — 정확히 몇 개월 전인지는
   * `current`/`previous` 차이로 판단해야 한다. */
  previous: string;
  /** 이 데이터셋을 생성한 시각(ISO 8601, UTC) */
  generatedAt: string;
  totals: {
    /** 최신 분기 전국 점포 수(원본 원시 행 수) */
    stores: number;
    /** 이전 분기 전국 점포 수 */
    prevStores: number;
    /** 파생값: 최신 분기에만 있는 상가업소번호 수(신규 추정) */
    opened: number;
    /** 파생값: 이전 분기에만 있는 상가업소번호 수(소멸 추정) */
    closed: number;
  };
  /** 데이터 출처와 opened/closed 의 파생값 성격을 설명하는 문구 */
  sourceNote: string;
  /** 빌드 시점에 계산한 데이터 정합성 점검 결과(참고용, UI에서 안 써도 됨) */
  sanityChecks?: {
    id_intersection: {
      common: number;
      prev_total: number;
      cur_total: number;
      ratio_vs_prev: number;
      ratio_vs_cur: number;
    };
    dong_code_scheme: {
      cur_dong_codes: number;
      prev_dong_codes: number;
      common: number;
      only_in_cur: number;
      only_in_prev: number;
      sample_only_in_cur: string[];
      sample_only_in_prev: string[];
    };
    coords: {
      cur: { rows: number; missing: number; missing_pct: number; out_of_range: number; out_of_range_pct: number };
      prev: { rows: number; missing: number; missing_pct: number; out_of_range: number; out_of_range_pct: number };
    };
    encoding: string;
    malformed_rows: { cur: number; prev: number };
  };
}

/** data/sigungu.json 의 원소 하나 (전국 시군구 요약) */
export interface SigunguSummary {
  /** 시군구코드(5자리, 원본 CSV의 시군구코드 컬럼) */
  code: string;
  /** 시도명 */
  sido: string;
  /** 시군구명 */
  name: string;
  /** 최신 분기 점포 수 */
  stores: number;
  /** 이전 분기 점포 수 */
  prevStores: number;
  /** 파생값: 신규 추정 점포 수(최신에만 존재하는 상가업소번호) */
  opened: number;
  /** 파생값: 소멸 추정 점포 수(이전에만 존재하는 상가업소번호) */
  closed: number;
  /** 파생값: (opened + closed) / prevStores, 소수 3자리. prevStores 가 0이면 0.
   * "점포가 그 기간 동안 얼마나 갈렸는가"를 나타내는 회전율 지표이며 0~1
   * 범위를 벗어날 수도 있다(교체가 매우 많으면 1 이상도 이론상 가능하지만
   * 실제 데이터에서는 대체로 0~0.5 수준). */
  turnoverRate: number;
}

/** data/dong/{시군구코드}.json 의 원소 하나 (그 시군구 안의 행정동 요약) */
export interface DongSummary {
  /** 행정동코드(원본 CSV의 행정동코드 컬럼) */
  code: string;
  /** 행정동명 */
  name: string;
  stores: number;
  prevStores: number;
  /** 파생값 */
  opened: number;
  /** 파생값 */
  closed: number;
  /** 파생값, 소수 3자리 */
  turnoverRate: number;
  /** 이 행정동에서 최신 분기 점포 수가 많은 업종중분류 상위 8개 */
  top: DongTopUpjong[];
}

export interface DongTopUpjong {
  /** 상권업종중분류코드 */
  code: string;
  /** 상권업종중분류명 */
  name: string;
  /** 최신 분기 이 업종의 점포 수 */
  count: number;
  /** 파생값: 최신 - 이전 분기 점포 수 차이(업종별 원시 카운트 차이이며,
   * opened/closed 처럼 상가업소번호 diff 를 낸 값은 아님) */
  delta: number;
}

/** data/upjong.json */
export interface UpjongTable {
  /** 상권업종대분류(10개) 전국 집계 */
  large: UpjongLargeRow[];
  /** 상권업종중분류(75개) 전국 집계 */
  middle: UpjongMiddleRow[];
}

export interface UpjongLargeRow {
  /** 상권업종대분류코드 */
  code: string;
  /** 상권업종대분류명 */
  name: string;
  /** 최신 분기 전국 점포 수 */
  stores: number;
  /** 파생값: 최신 - 이전 분기 전국 점포 수 차이 */
  delta: number;
}

export interface UpjongMiddleRow {
  /** 상권업종중분류코드 */
  code: string;
  /** 상권업종중분류명 */
  name: string;
  /** 이 중분류가 속한 상권업종대분류코드 */
  largeCode: string;
  /** 최신 분기 전국 점포 수 */
  stores: number;
  /** 파생값: 최신 - 이전 분기 전국 점포 수 차이 */
  delta: number;
}

/** data/changes/{시군구코드}.json */
export interface SigunguChanges {
  /** 파생값: 이 시군구에서 신규로 추정되는 점포 목록(2MB 초과 시 행정동별로
   * 고르게 샘플링됨 — 그 경우 실제 개수는 openedTotal 을 봐야 함) */
  opened: ChangeItem[];
  /** 파생값: 이 시군구에서 소멸로 추정되는 점포 목록(위와 동일한 샘플링 규칙) */
  closed: ChangeItem[];
  /** opened 배열이 샘플링되지 않았다면 opened.length 와 같다.
   * 샘플링됐다면 원래(전체) 신규 추정 점포 수. */
  openedTotal: number;
  /** closed 배열이 샘플링되지 않았다면 closed.length 와 같다.
   * 샘플링됐다면 원래(전체) 소멸 추정 점포 수. */
  closedTotal: number;
}

export interface ChangeItem {
  /** 상호명 */
  name: string;
  /** 지점명. 값이 없으면(빈 문자열) 필드 자체가 생략된다. */
  branch?: string;
  /** 상권업종중분류명 */
  upjong: string;
  /** 행정동명 */
  dong: string;
  /** 도로명주소(원본 CSV의 도로명주소 컬럼, 전체 주소) */
  road: string;
  /** 위도. 좌표가 없거나 파싱 실패한 원본 행은 이 항목 자체가 제외된다. */
  lat: number;
  /** 경도 */
  lon: number;
}

/** data/rank/upjong-{업종중분류코드}.json (전국 점포 수 상위 30개 업종만 존재) */
export interface UpjongRank {
  /** 상권업종중분류코드 */
  code: string;
  /** 상권업종중분류명 */
  name: string;
  /** 이 업종의 점포가 많은 시군구 상위 50개(최신 분기 기준, 내림차순) */
  rows: UpjongRankRow[];
}

export interface UpjongRankRow {
  /** 시군구코드 */
  sigunguCode: string;
  /** 시도명 */
  sido: string;
  /** 시군구명 */
  name: string;
  /** 최신 분기 이 업종의 점포 수 */
  stores: number;
  /** 인구 만 명당 점포 수 등 정규화 지표. 생성 스크립트가 계산하지 않는
   * 한 생략될 수 있으므로 선택 필드로 둔다. */
  per10k?: number;
}
