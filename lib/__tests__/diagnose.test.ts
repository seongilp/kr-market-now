import assert from 'node:assert/strict';
import { test } from 'node:test';

import { checkUpjong, regionType, specialization } from '../diagnose';
import type { UpjongStat } from '../insight-types';

const national = { stores: 2_772_484, prevStores: 2_697_338, turnoverRate: 0.3 };

test('동네 유형: 성장·교체 모두 높으면 boom', () => {
  assert.equal(regionType({ stores: 1200, prevStores: 1000, turnoverRate: 0.45 }, national).type, 'boom');
});

test('동네 유형: 성장은 낮고 교체만 높으면 churn', () => {
  assert.equal(regionType({ stores: 1005, prevStores: 1000, turnoverRate: 0.4 }, national).type, 'churn');
});

test('동네 유형: 둘 다 낮으면 steady', () => {
  assert.equal(regionType({ stores: 1010, prevStores: 1000, turnoverRate: 0.2 }, national).type, 'steady');
});

test('동네 유형: 순감이면 decline (교체율과 무관)', () => {
  assert.equal(regionType({ stores: 900, prevStores: 1000, turnoverRate: 0.5 }, national).type, 'decline');
});

test('특화 지수: 비중이 전국의 두 배면 2.0', () => {
  assert.equal(specialization({ stores: 20 }, 100, { stores: 1000 }, 10_000), 2);
  assert.equal(specialization({ stores: 0 }, 0, { stores: 1000 }, 10_000), 0);
});

function stat(over: Partial<UpjongStat>): UpjongStat {
  return { code: 'I201', name: '한식', stores: 100, prevStores: 100, opened: 20, closed: 20, closeRate: 0.2, openRate: 0.2, ...over };
}

test('창업 체크: 소멸률 높고 몰려 있고 순감이면 위험', () => {
  const r = checkUpjong(stat({ closeRate: 0.3, stores: 300, opened: 10, closed: 40 }), 1000, stat({ closeRate: 0.2, stores: 1000 }), 10_000);
  assert.equal(r.verdict, 'risky');
  assert.ok(r.reasons.some((s) => s.includes('전국 20.0%보다 높습니다')));
  assert.ok(r.reasons.some((s) => s.includes('배로 몰려')));
});

test('창업 체크: 전국과 비슷하고 순증이면 나쁘지 않음', () => {
  const r = checkUpjong(stat({ closeRate: 0.21, opened: 25, closed: 15 }), 1000, stat({ closeRate: 0.2, stores: 1000 }), 10_000);
  assert.equal(r.verdict, 'good');
  assert.ok(r.reasons.some((s) => s.includes('순증')));
});

test('창업 체크: 표본이 작으면 경고 문장이 앞에 붙는다', () => {
  const r = checkUpjong(stat({ prevStores: 5, stores: 5, closeRate: 0.2 }), 1000, stat({ closeRate: 0.2, stores: 1000 }), 10_000);
  assert.match(r.reasons[0], /5곳뿐/);
});
