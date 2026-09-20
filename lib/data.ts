import 'server-only';

import { readFile } from 'node:fs/promises';
import path from 'node:path';

import metaJson from '@/data/meta.json';
import sigunguJson from '@/data/sigungu.json';
import upjongJson from '@/data/upjong.json';
import type { DongSummary, Meta, SigunguChanges, SigunguSummary, UpjongRank, UpjongTable } from '@/lib/data-types';

/** 작은 파일은 번들에 직접 싣고, 시군구별 파일은 빌드 시점에 디스크에서 읽는다(페이지는 전부 정적 생성). */
export const meta = metaJson as Meta;
export const sigunguList = sigunguJson as SigunguSummary[];
export const upjong = upjongJson as UpjongTable;

const DATA_DIR = path.join(process.cwd(), 'data');

async function readJson<T>(...segments: string[]): Promise<T> {
  return JSON.parse(await readFile(path.join(DATA_DIR, ...segments), 'utf8')) as T;
}

export function getSigungu(code: string): SigunguSummary | undefined {
  return sigunguList.find((s) => s.code === code);
}

export function dongList(code: string): Promise<DongSummary[]> {
  return readJson<DongSummary[]>('dong', `${code}.json`);
}

export function changes(code: string): Promise<SigunguChanges> {
  return readJson<SigunguChanges>('changes', `${code}.json`);
}

export function upjongRank(code: string): Promise<UpjongRank> {
  return readJson<UpjongRank>('rank', `upjong-${code}.json`);
}

/** 분기 코드(202606) → "2026년 6월" */
export function quarterLabel(ym: string): string {
  return `${ym.slice(0, 4)}년 ${Number(ym.slice(4, 6))}월`;
}

export function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function signed(value: number): string {
  return value > 0 ? `+${value.toLocaleString()}` : value.toLocaleString();
}
