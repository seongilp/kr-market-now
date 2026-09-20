/** 지표를 사람이 읽는 판단으로 바꾸는 순수 함수들. 네트워크·파일 없음 — 테스트 대상. */

import type { UpjongStat } from '@/lib/insight-types';

export type RegionType = 'boom' | 'churn' | 'steady' | 'decline';

export interface RegionTypeResult {
  type: RegionType;
  label: string;
  description: string;
}

/**
 * 동네 유형: 성장률(점포 순증 비율)과 교체율을 전국과 비교해 네 가지로 나눈다.
 * - boom: 성장·교체 모두 전국 이상 — 신도시·택지지구처럼 가게가 빠르게 들어서는 곳
 * - churn: 성장은 전국 이하인데 교체는 전국 이상 — 생기는 만큼 사라지는 곳
 * - steady: 둘 다 전국 이하 — 가게가 오래 가는 곳
 * - decline: 성장이 마이너스 — 사라지는 게 더 많은 곳
 */
export function regionType(
  region: { stores: number; prevStores: number; turnoverRate: number },
  national: { stores: number; prevStores: number; turnoverRate: number },
): RegionTypeResult {
  const growth = region.prevStores === 0 ? 0 : region.stores / region.prevStores - 1;
  const natGrowth = national.stores / national.prevStores - 1;
  const highTurnover = region.turnoverRate >= national.turnoverRate;

  if (growth < 0) {
    return { type: 'decline', label: '줄어드는 동네', description: '1년 사이 생긴 가게보다 사라진 가게가 많습니다.' };
  }
  if (growth >= natGrowth && highTurnover) {
    return {
      type: 'boom',
      label: '빠르게 채워지는 동네',
      description: '가게가 전국 평균보다 빠르게 늘고, 자주 바뀝니다. 신도시·개발지에서 흔한 모습입니다.',
    };
  }
  if (highTurnover) {
    return {
      type: 'churn',
      label: '자주 바뀌는 동네',
      description: '가게 수는 크게 늘지 않는데 교체가 잦습니다. 생기는 만큼 사라집니다.',
    };
  }
  return { type: 'steady', label: '오래 가는 동네', description: '교체가 전국 평균보다 드뭅니다. 가게가 비교적 오래 버팁니다.' };
}

/**
 * 특화 지수(location quotient): 이 동네에서 그 업종이 차지하는 비중 ÷ 전국에서 차지하는 비중.
 * 1.0 이면 전국과 같고, 2.0 이면 전국의 두 배로 몰려 있다.
 */
export function specialization(
  regionStat: { stores: number },
  regionTotal: number,
  nationalStat: { stores: number },
  nationalTotal: number,
): number {
  if (regionTotal === 0 || nationalTotal === 0 || nationalStat.stores === 0) return 0;
  return regionStat.stores / regionTotal / (nationalStat.stores / nationalTotal);
}

export type Verdict = 'good' | 'caution' | 'risky';

export interface CheckResult {
  verdict: Verdict;
  label: string;
  reasons: string[];
  /** 이 동네 1년 소멸률 */
  closeRate: number;
  /** 전국 1년 소멸률 */
  nationalCloseRate: number;
  /** 특화 지수 */
  lq: number;
  /** 순증(신규-소멸) */
  net: number;
}

const LQ_CROWDED = 1.5;
const RISK_CLOSE_RATE_GAP = 0.03;
const MIN_SAMPLE = 20;

/** "이 동네에서 이 업종 해도 되나" — 소멸률·밀집도·순증을 전국과 비교해 세 단계로 판정한다 */
export function checkUpjong(
  region: UpjongStat,
  regionTotal: number,
  national: UpjongStat,
  nationalTotal: number,
): CheckResult {
  const lq = specialization(region, regionTotal, national, nationalTotal);
  const net = region.opened - region.closed;
  const reasons: string[] = [];
  let risk = 0;

  if (region.prevStores < MIN_SAMPLE) {
    reasons.push(`이 동네에 ${national.name} 가게가 ${region.prevStores}곳뿐이라 통계가 흔들립니다.`);
  }
  if (region.closeRate >= national.closeRate + RISK_CLOSE_RATE_GAP) {
    risk += 2;
    reasons.push(
      `1년 사이 ${pctText(region.closeRate)}가 사라졌습니다. 전국 ${pctText(national.closeRate)}보다 높습니다.`,
    );
  } else if (region.closeRate <= national.closeRate - RISK_CLOSE_RATE_GAP) {
    risk -= 1;
    reasons.push(`1년 소멸률 ${pctText(region.closeRate)}로 전국 ${pctText(national.closeRate)}보다 낮습니다.`);
  } else {
    reasons.push(`1년 소멸률 ${pctText(region.closeRate)}로 전국(${pctText(national.closeRate)})과 비슷합니다.`);
  }

  if (lq >= LQ_CROWDED) {
    risk += 1;
    reasons.push(`이 업종이 전국 평균의 ${lq.toFixed(1)}배로 몰려 있습니다. 경쟁이 셉니다.`);
  } else if (lq > 0 && lq < 0.7) {
    reasons.push(`이 업종 비중이 전국 평균의 ${lq.toFixed(1)}배로 낮습니다. 빈자리일 수도, 수요가 없는 것일 수도 있습니다.`);
  }

  if (net < 0) {
    risk += 1;
    reasons.push(`1년 사이 ${Math.abs(net)}곳이 순감했습니다. 들어오는 것보다 나가는 게 많습니다.`);
  } else if (net > 0) {
    reasons.push(`1년 사이 ${net}곳이 순증했습니다.`);
  }

  const verdict: Verdict = risk >= 2 ? 'risky' : risk >= 1 ? 'caution' : 'good';
  const label = verdict === 'risky' ? '위험 신호' : verdict === 'caution' ? '주의' : '나쁘지 않음';
  return { verdict, label, reasons, closeRate: region.closeRate, nationalCloseRate: national.closeRate, lq, net };
}

function pctText(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}
