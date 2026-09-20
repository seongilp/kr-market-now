import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { ArrowRight } from 'lucide-react';

import { RateBar } from '@/components/rate-bar';
import { Sparkline } from '@/components/sparkline';
import { Stat } from '@/components/stat';
import { meta, pct, sigunguList, signed } from '@/lib/data';
import { largeNameOf, national, regionInsights, yearlySeries } from '@/lib/insights';
import type { MiddleUpjongStat, SmallUpjongStat } from '@/lib/insight-types';

const TOP = 10;
const MIN_REGION_UPJONG = 30;

export function generateStaticParams() {
  return national.middle.map((m) => ({ code: m.code }));
}

export async function generateMetadata({ params }: PageProps<'/u/[code]'>): Promise<Metadata> {
  const { code } = await params;
  const row = national.middle.find((u) => u.code === code);
  return row ? { title: `${row.name} 업종 리포트`, description: `${row.name}의 생존율, 5년 추이, 어디서 늘고 줄었나` } : {};
}

/** 287개 시군구 파일에서 이 업종 줄만 뽑는다(빌드 시점 한 번) */
async function regionRows(code: string): Promise<{ code: string; sido: string; name: string; stat: MiddleUpjongStat }[]> {
  const out: { code: string; sido: string; name: string; stat: MiddleUpjongStat }[] = [];
  for (const r of sigunguList) {
    const ins = await regionInsights(r.code);
    const stat = ins.middle.find((m) => m.code === code);
    if (stat && stat.prevStores >= MIN_REGION_UPJONG && stat.stores > 0) out.push({ code: r.code, sido: r.sido, name: r.name, stat });
  }
  return out;
}

export default async function UpjongPage({ params }: PageProps<'/u/[code]'>) {
  const { code } = await params;
  const u = national.middle.find((m) => m.code === code);
  if (!u) notFound();

  const nationalClose = meta.totals.closed / meta.totals.prevStores;
  const series = yearlySeries('middle', u);
  const years = national.yearly.years;
  const smalls = national.small.filter((s) => s.middleCode === code).sort((a, b) => b.stores - a.stores);
  const rows = await regionRows(code);
  const mostNet = [...rows].sort((a, b) => b.stat.opened - b.stat.closed - (a.stat.opened - a.stat.closed)).slice(0, TOP);
  const mostClose = [...rows].sort((a, b) => b.stat.closeRate - a.stat.closeRate).slice(0, TOP);
  const leastClose = [...rows].sort((a, b) => a.stat.closeRate - b.stat.closeRate).slice(0, TOP);

  return (
    <div className="space-y-10">
      <nav className="text-sm text-muted-foreground">
        <Link href="/" className="hover:text-foreground">
          홈
        </Link>{' '}
        / {largeNameOf(u.code)}
      </nav>
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">{u.name}</h1>
        <p className="text-sm text-muted-foreground">전국 {u.stores.toLocaleString()}곳 · 1년 전 {u.prevStores.toLocaleString()}곳</p>
      </header>

      <section className="grid gap-3 sm:grid-cols-4">
        <Stat label="1년 소멸률" value={pct(u.closeRate)} sub={`전체 업종 평균 ${pct(nationalClose)}`} tone={u.closeRate > nationalClose ? 'down' : 'up'} />
        <Stat label="1년 신규율" value={pct(u.openRate)} sub={`신규 ${u.opened.toLocaleString()}곳`} />
        <Stat label="순증" value={signed(u.stores - u.prevStores)} tone={u.stores >= u.prevStores ? 'up' : 'down'} />
        {series && years.length >= 2 && (
          <div className="rounded-2xl border border-[#E5E8EB] bg-white p-4">
            <div className="text-sm text-muted-foreground">
              {years[0]}→{years[years.length - 1]} 추이
            </div>
            <div className="mt-1 flex items-center gap-3">
              <Sparkline values={series} width={140} height={40} />
              <span className="text-lg font-bold tabular-nums">{series[0] === 0 ? '-' : `${((series[series.length - 1] / series[0] - 1) * 100).toFixed(0)}%`}</span>
            </div>
          </div>
        )}
      </section>

      {series && (
        <section>
          <h2 className="mb-3 text-lg font-semibold">연도별 전국 점포 수</h2>
          <div className="overflow-x-auto rounded-2xl border border-[#E5E8EB] bg-white">
            <table className="w-full text-sm">
              <tbody>
                <tr className="bg-muted/60">
                  {years.map((y) => (
                    <th key={y} className="px-3 py-2 text-right font-medium">
                      {y}
                    </th>
                  ))}
                </tr>
                <tr>
                  {series.map((v, i) => (
                    <td key={i} className="px-3 py-2 text-right tabular-nums">
                      {v.toLocaleString()}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      )}

      {smalls.length > 1 && (
        <section>
          <h2 className="mb-3 text-lg font-semibold">세부 업종</h2>
          <ul className="divide-y rounded-2xl border border-[#E5E8EB] bg-white">
            {smalls.map((s) => (
              <SmallRow key={s.code} s={s} baseline={u.closeRate} />
            ))}
          </ul>
        </section>
      )}

      <section className="grid gap-6 lg:grid-cols-3">
        <RegionList title="가장 많이 늘어난 곳" rows={mostNet} value={(s) => signed(s.opened - s.closed)} />
        <RegionList title="가장 자주 사라진 곳" rows={mostClose} value={(s) => pct(s.closeRate)} tone="down" />
        <RegionList title="가장 오래 버틴 곳" rows={leastClose} value={(s) => pct(s.closeRate)} tone="up" />
      </section>
      <p className="text-xs text-muted-foreground">지역 비교는 1년 전 {u.name} 가게가 {MIN_REGION_UPJONG}곳 이상인 시군구만.</p>
    </div>
  );
}

function SmallRow({ s, baseline }: { s: SmallUpjongStat; baseline: number }) {
  const series = yearlySeries('small', s);
  return (
    <li className="p-3">
      <div className="flex items-center gap-3">
        <span className="flex-1 text-sm">{s.name}</span>
        {series && <Sparkline values={series} width={80} height={24} color="#8B95A1" />}
        <span className="w-20 text-right text-sm font-semibold tabular-nums">{pct(s.closeRate)}</span>
        <span className="w-20 text-right text-xs text-muted-foreground tabular-nums">{s.stores.toLocaleString()}곳</span>
      </div>
      <div className="mt-1.5">
        <RateBar value={s.closeRate} baseline={baseline} />
      </div>
    </li>
  );
}

function RegionList({
  title,
  rows,
  value,
  tone,
}: {
  title: string;
  rows: { code: string; sido: string; name: string; stat: MiddleUpjongStat }[];
  value: (s: MiddleUpjongStat) => string;
  tone?: 'up' | 'down';
}) {
  const color = tone === 'up' ? 'text-primary' : tone === 'down' ? 'text-[#E5484D]' : '';
  return (
    <div>
      <h2 className="mb-3 text-lg font-semibold">{title}</h2>
      <ol className="divide-y rounded-2xl border border-[#E5E8EB] bg-white">
        {rows.map((r) => (
          <li key={r.code}>
            <Link href={`/r/${r.code}`} className="flex items-center gap-3 p-3 hover:bg-accent">
              <span className="flex-1 text-sm">
                {r.sido} <strong>{r.name}</strong>
              </span>
              <span className={`text-sm font-semibold tabular-nums ${color}`}>{value(r.stat)}</span>
              <span className="w-14 text-right text-xs text-muted-foreground tabular-nums">{r.stat.stores}곳</span>
              <ArrowRight className="size-4 text-muted-foreground" aria-hidden />
            </Link>
          </li>
        ))}
      </ol>
    </div>
  );
}
