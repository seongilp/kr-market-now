import 'server-only';

import { readFile } from 'node:fs/promises';
import path from 'node:path';

import nationalJson from '@/data/insights/national.json';
import upjongJson from '@/data/upjong.json';
import type { BrandStat, NationalInsights, RegionInsights, UpjongStat } from '@/lib/insight-types';

export const national = nationalJson as unknown as NationalInsights;

const REGION_DIR = path.join(process.cwd(), 'data', 'insights', 'region');

export async function regionInsights(code: string): Promise<RegionInsights> {
  return JSON.parse(await readFile(path.join(REGION_DIR, `${code}.json`), 'utf8')) as RegionInsights;
}

/** 표본이 너무 작으면 비율이 튄다 — 랭킹류는 이 기준 이상만 */
export const MIN_STORES_FOR_RATE = 1000;

export function nationalMiddle(code: string): UpjongStat | undefined {
  return national.middle.find((m) => m.code === code);
}

export function sumStores(rows: UpjongStat[]): number {
  return rows.reduce((acc, r) => acc + r.stores, 0);
}

/** 5년 추이에서 (마지막 / 처음 - 1). 시작이 0이면 undefined */
export function fiveYearGrowth(series: number[] | undefined): number | undefined {
  if (!series || series.length < 2 || series[0] === 0) return undefined;
  return series[series.length - 1] / series[0] - 1;
}

/**
 * 1년 전 점포가 지금의 30% 미만(또는 그 반대)이면 실제 출점·폐점이 아니라 원본의 상호 표기 방식이
 * 바뀐 경우일 가능성이 크다(예: 2025-06 "스타벅스강남" → 2026-06 "스타벅스" + 지점명 분리). 랭킹에서 뺀다.
 */
export function isSuspiciousBrandDelta(b: { stores: number; prevStores: number }): boolean {
  const lo = Math.min(b.stores, b.prevStores);
  const hi = Math.max(b.stores, b.prevStores);
  return hi >= 50 && lo < hi * 0.3;
}

const LARGE_NAME = new Map((upjongJson as { large: { code: string; name: string }[] }).large.map((l) => [l.code, l.name]));
const MIDDLE_LARGE = new Map((upjongJson as { middle: { code: string; largeCode: string }[] }).middle.map((m) => [m.code, m.largeCode]));

/** 중분류 코드 → 대분류명 (insights 의 middle 에는 대분류가 없어서 업종표에서 찾는다) */
export function largeNameOf(middleCode: string): string {
  return LARGE_NAME.get(MIDDLE_LARGE.get(middleCode) ?? '') ?? '';
}

/** 연도별 추이는 업종명이 키다(코드 재부여에 안전하게 이름으로 집계했다). 코드로도 한 번 찾아본다. */
export function yearlySeries(kind: 'middle' | 'small', stat: { code: string; name: string }): number[] | undefined {
  const table = national.yearly[kind];
  return table[stat.name] ?? table[stat.code];
}

const norm = (v: string) => v.replace(/[^0-9A-Za-z가-힣]/g, '');
const UPJONG_NAMES = new Set([
  ...national.middle.map((m) => norm(m.name)),
  ...national.small.map((m) => norm(m.name)),
  ...(upjongJson as { large: { name: string }[] }).large.map((l) => norm(l.name)),
]);

/** "슈퍼마켓", "경영컨설팅업"처럼 간판이 아니라 업종명을 상호로 적은 것은 브랜드가 아니다 */
export function isGenericBrandName(name: string): boolean {
  const n = norm(name);
  return UPJONG_NAMES.has(n) || /(업|기관|사무소|센터|점포|상회|청소|수리|학원|마트|식당|분식)$/.test(n) || n.length < 2;
}

export function realBrands(rows: BrandStat[]): BrandStat[] {
  return rows.filter((b) => !isGenericBrandName(b.name) && !isSuspiciousBrandDelta(b));
}
