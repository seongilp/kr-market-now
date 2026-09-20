import 'server-only';

import { readFile } from 'node:fs/promises';
import path from 'node:path';

import metaJson from '@/data/meta.json';
import sigunguJson from '@/data/sigungu.json';
import upjongJson from '@/data/upjong.json';
import dotsJson from '@/data/dots.json';
import type { DongSummary, Dot, Meta, SigunguChanges, SigunguSummary, UpjongRank, UpjongTable } from '@/lib/data-types';

/** 작은 파일은 번들에 직접 싣고, 시군구별 파일은 빌드 시점에 디스크에서 읽는다(페이지는 전부 정적 생성). */
export const meta = metaJson as Meta;
export const sigunguList = sigunguJson as SigunguSummary[];
export const upjong = upjongJson as UpjongTable;

const DATA_DIR = path.join(process.cwd(), 'data');
// 변화 목록은 지도(클라이언트)도 같은 파일을 URL 로 받아 쓰기 때문에 public 아래에 둔다
const PUBLIC_DATA_DIR = path.join(process.cwd(), 'public', 'data');

async function readJson<T>(dir: string, ...segments: string[]): Promise<T> {
  return JSON.parse(await readFile(path.join(dir, ...segments), 'utf8')) as T;
}

export function getSigungu(code: string): SigunguSummary | undefined {
  return sigunguList.find((s) => s.code === code);
}

export function dongList(code: string): Promise<DongSummary[]> {
  return readJson<DongSummary[]>(DATA_DIR, 'dong', `${code}.json`);
}

export function changes(code: string): Promise<SigunguChanges> {
  return readJson<SigunguChanges>(PUBLIC_DATA_DIR, 'changes', `${code}.json`);
}

export function upjongRank(code: string): Promise<UpjongRank> {
  return readJson<UpjongRank>(DATA_DIR, 'rank', `upjong-${code}.json`);
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

const DOTS = dotsJson as Dot[];

/** 시군구의 대표 좌표 — 그 시군구 동네 원들의 평균. 동네가 없으면 undefined */
export function regionCenter(code: string): { lat: number; lon: number } | undefined {
  const mine = DOTS.filter((d) => d.sigunguCode === code);
  if (mine.length === 0) return undefined;
  return {
    lat: Number((mine.reduce((a, d) => a + d.lat, 0) / mine.length).toFixed(5)),
    lon: Number((mine.reduce((a, d) => a + d.lon, 0) / mine.length).toFixed(5)),
  };
}
