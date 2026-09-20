import Link from 'next/link';
import { ArrowDownRight, ArrowUpRight } from 'lucide-react';

import { RegionSearch } from '@/components/region-search';
import { Stat } from '@/components/stat';
import { meta, pct, quarterLabel, sigunguList, signed, upjong } from '@/lib/data';

const RANK_SIZE = 10;
const MIN_STORES_FOR_RANK = 3000; // 점포가 아주 적은 군 지역은 교체율이 튀어서 순위에서 뺀다

export default function Home() {
  const rankable = sigunguList.filter((r) => r.prevStores >= MIN_STORES_FOR_RANK);
  const hottest = [...rankable].sort((a, b) => b.turnoverRate - a.turnoverRate).slice(0, RANK_SIZE);
  const grown = [...sigunguList].sort((a, b) => b.stores - b.prevStores - (a.stores - a.prevStores)).slice(0, RANK_SIZE);
  const risingUpjong = [...upjong.middle].sort((a, b) => b.delta - a.delta).slice(0, 8);
  const fallingUpjong = [...upjong.middle].sort((a, b) => a.delta - b.delta).slice(0, 8);
  const { stores, prevStores, opened, closed } = meta.totals;

  return (
    <div className="space-y-10">
      <section className="-mx-4 -mt-6 space-y-4 bg-gradient-to-b from-[var(--brand-soft)] to-white px-4 pt-10 pb-6 sm:rounded-b-3xl">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">
          1년 사이 <span className="text-primary">{opened.toLocaleString()}곳</span>이 생기고{' '}
          <span className="text-[#E5484D]">{closed.toLocaleString()}곳</span>이 사라졌습니다
        </h1>
        <p className="text-muted-foreground">
          전국 상가 {stores.toLocaleString()}곳을 {quarterLabel(meta.previous)}과 {quarterLabel(meta.current)} 두 시점으로
          비교했습니다. 우리 동네에서 무엇이 생기고 무엇이 문을 닫았는지 찾아보세요.
        </p>
        <RegionSearch regions={sigunguList} />
        <Link
          href="/map"
          className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
        >
          전국 지도에서 보기 <ArrowUpRight className="size-4" aria-hidden />
        </Link>
      </section>

      <section className="grid gap-3 sm:grid-cols-4">
        <Stat label="전국 상가" value={stores.toLocaleString()} sub={`1년 전 ${prevStores.toLocaleString()}곳`} />
        <Stat label="새로 생긴 곳" value={opened.toLocaleString()} tone="up" sub="이전 분기에 없던 상가" />
        <Stat label="사라진 곳" value={closed.toLocaleString()} tone="down" sub="이전 분기에만 있던 상가" />
        <Stat label="전국 교체율" value={pct((opened + closed) / prevStores)} sub="(신규+소멸)÷1년 전 상가 수" />
      </section>

      <section>
        <h2 className="mb-1 text-lg font-semibold">가장 많이 바뀐 동네</h2>
        <p className="mb-3 text-sm text-muted-foreground">
          교체율이 높다는 건 그만큼 가게가 자주 생기고 사라진다는 뜻입니다. 상가 {MIN_STORES_FOR_RANK.toLocaleString()}곳
          이상인 시군구만 비교했습니다.
        </p>
        <ol className="divide-y rounded-2xl border border-[#E5E8EB] bg-white">
          {hottest.map((r, i) => (
            <li key={r.code}>
              <Link href={`/r/${r.code}`} className="flex items-center gap-3 p-3 hover:bg-accent">
                <span className="w-5 text-center text-sm text-muted-foreground tabular-nums">{i + 1}</span>
                <span className="flex-1 text-sm">
                  {r.sido} <strong>{r.name}</strong>
                </span>
                <span className="text-sm font-semibold text-primary tabular-nums">{pct(r.turnoverRate)}</span>
                <span className="hidden w-32 text-right text-xs text-muted-foreground tabular-nums sm:block">
                  +{r.opened.toLocaleString()} / -{r.closed.toLocaleString()}
                </span>
              </Link>
            </li>
          ))}
        </ol>
      </section>

      <section className="grid gap-6 sm:grid-cols-2">
        <div>
          <h2 className="mb-3 flex items-center gap-1 text-lg font-semibold">
            <ArrowUpRight className="size-4 text-primary" aria-hidden /> 늘어난 업종
          </h2>
          <UpjongList rows={risingUpjong} />
        </div>
        <div>
          <h2 className="mb-3 flex items-center gap-1 text-lg font-semibold">
            <ArrowDownRight className="size-4 text-[#E5484D]" aria-hidden /> 줄어든 업종
          </h2>
          <UpjongList rows={fallingUpjong} />
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">상가가 가장 많이 늘어난 곳</h2>
        <ol className="divide-y rounded-2xl border border-[#E5E8EB] bg-white">
          {grown.map((r) => (
            <li key={r.code}>
              <Link href={`/r/${r.code}`} className="flex items-center gap-3 p-3 hover:bg-accent">
                <span className="flex-1 text-sm">
                  {r.sido} <strong>{r.name}</strong>
                </span>
                <span className="text-sm font-semibold text-primary tabular-nums">{signed(r.stores - r.prevStores)}</span>
                <span className="w-24 text-right text-xs text-muted-foreground tabular-nums">
                  {r.stores.toLocaleString()}곳
                </span>
              </Link>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function UpjongList({ rows }: { rows: { code: string; name: string; stores: number; delta: number }[] }) {
  return (
    <ul className="divide-y rounded-2xl border border-[#E5E8EB] bg-white">
      {rows.map((u) => (
        <li key={u.code} className="flex items-center gap-3 p-3">
          <span className="flex-1 text-sm">{u.name}</span>
          <span className={`text-sm font-semibold tabular-nums ${u.delta >= 0 ? 'text-primary' : 'text-[#E5484D]'}`}>
            {signed(u.delta)}
          </span>
          <span className="w-24 text-right text-xs text-muted-foreground tabular-nums">
            {u.stores.toLocaleString()}곳
          </span>
        </li>
      ))}
    </ul>
  );
}
