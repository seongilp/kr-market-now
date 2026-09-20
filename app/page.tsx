import Link from 'next/link';
import { ArrowRight, MapPinned } from 'lucide-react';

import { RateBar } from '@/components/rate-bar';
import { RegionSearch } from '@/components/region-search';
import { Sparkline } from '@/components/sparkline';
import { meta, pct, quarterLabel, sigunguList, signed } from '@/lib/data';
import { MIN_STORES_FOR_RATE, fiveYearGrowth, national, realBrands, yearlySeries } from '@/lib/insights';
import type { BrandStat, SmallUpjongStat, Transition, UpjongStat } from '@/lib/insight-types';

const RANK = 10;
const MIN_REGION_STORES = 3000;
const MIN_SMALL_FOR_TREND = 500;
const MIN_BRAND_STORES = 100;

export default function Home() {
  const { stores, prevStores, opened, closed } = meta.totals;
  const nationalClose = closed / prevStores;

  const rated = national.middle.filter((m) => m.prevStores >= MIN_STORES_FOR_RATE);
  const riskiest = [...rated].sort((a, b) => b.closeRate - a.closeRate).slice(0, RANK);
  const safest = [...rated].sort((a, b) => a.closeRate - b.closeRate).slice(0, RANK);

  const switches = national.transitions.filter((t) => t.fromCode !== t.toCode).slice(0, RANK);
  const sameUpjong = national.transitions.filter((t) => t.fromCode === t.toCode).reduce((a, t) => a + t.count, 0);
  const matched = national.transitionMatched || 1;

  const trend = national.small
    .filter((s) => s.stores >= MIN_SMALL_FOR_TREND)
    .map((s) => ({ ...s, series: yearlySeries('small', s) ?? [], growth: fiveYearGrowth(yearlySeries('small', s)) }))
    .filter((s): s is typeof s & { growth: number } => s.growth !== undefined);
  const rising = [...trend].sort((a, b) => b.growth - a.growth).slice(0, 8);
  const falling = [...trend].sort((a, b) => a.growth - b.growth).slice(0, 8);

  const brands = realBrands(national.brands).filter((b) => b.prevStores >= MIN_BRAND_STORES || b.stores >= MIN_BRAND_STORES);
  const brandUp = [...brands].sort((a, b) => b.stores - b.prevStores - (a.stores - a.prevStores)).slice(0, 8);
  const brandDown = [...brands].sort((a, b) => a.stores - a.prevStores - (b.stores - b.prevStores)).slice(0, 8);

  const hottest = sigunguList
    .filter((r) => r.prevStores >= MIN_REGION_STORES && r.stores > 0)
    .sort((a, b) => b.turnoverRate - a.turnoverRate)
    .slice(0, RANK);

  const years = national.yearly.years;
  const yearSpan = years.length >= 2 ? `${years[0]}→${years[years.length - 1]}` : '';

  return (
    <div className="space-y-12">
      <section className="-mx-4 -mt-6 space-y-4 bg-gradient-to-b from-[var(--brand-soft)] to-white px-4 pt-10 pb-6 sm:rounded-b-3xl">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">
          가게는 <span className="text-primary">어디서, 무엇이</span> 살아남는가
        </h1>
        <p className="text-muted-foreground">
          전국 상가 {stores.toLocaleString()}곳의 1년 변화({quarterLabel(meta.previous)} → {quarterLabel(meta.current)})에서
          업종별 생존율, 사라진 자리에 들어온 업종, 브랜드 출점·폐점, 5년 추이를 읽어냅니다.
        </p>
        <RegionSearch regions={sigunguList} />
        <Link href="/map" className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline">
          <MapPinned className="size-4" aria-hidden /> 전국 지도에서 신규·소멸 보기
        </Link>
      </section>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Headline
          kicker="1년 안에 가장 많이 사라진 업종"
          value={riskiest[0]?.name ?? '-'}
          detail={`${pct(riskiest[0]?.closeRate ?? 0)}가 문을 닫았습니다. 전국 평균 ${pct(nationalClose)}`}
          tone="down"
        />
        <Headline
          kicker="가장 오래 버티는 업종"
          value={safest[0]?.name ?? '-'}
          detail={`1년 소멸률 ${pct(safest[0]?.closeRate ?? 0)}`}
          tone="up"
        />
        <Headline
          kicker="사라진 자리, 같은 업종이 다시"
          value={pct(sameUpjong / matched)}
          detail={`자리를 이어받은 ${matched.toLocaleString()}쌍 중 같은 업종이 다시 들어온 비율`}
        />
        <Headline
          kicker={`${yearSpan} 가장 빨리 늘어난 업종`}
          value={rising[0]?.name ?? '-'}
          detail={rising[0] ? `${years[0]}년 ${rising[0].series[0].toLocaleString()}곳 → 지금 ${rising[0].stores.toLocaleString()}곳` : ''}
          tone="up"
        />
      </section>

      <section>
        <h2 className="text-lg font-semibold">1년 안에 문 닫을 확률</h2>
        <p className="mb-3 text-sm text-muted-foreground">
          1년 전 있던 가게 중 지금 사라진 비율입니다. 전국 {MIN_STORES_FOR_RATE.toLocaleString()}곳 이상인 업종만. 선은 전국 평균.
        </p>
        <div className="grid gap-6 lg:grid-cols-2">
          <RateList title="가장 자주 사라지는 업종" rows={riskiest} baseline={nationalClose} />
          <RateList title="가장 오래 가는 업종" rows={safest} baseline={nationalClose} />
        </div>
      </section>

      <section>
        <h2 className="text-lg font-semibold">사라진 가게 자리에 뭐가 들어왔나</h2>
        <p className="mb-3 text-sm text-muted-foreground">
          같은 주소·층·호에서 사라진 가게와 새로 생긴 가게를 이어 붙인 {matched.toLocaleString()}쌍. 같은 업종 재입점(
          {pct(sameUpjong / matched)})을 뺀 업종 전환만 보여줍니다.
        </p>
        <ol className="divide-y rounded-2xl border border-[#E5E8EB] bg-white">
          {switches.map((t) => (
            <TransitionRow key={`${t.fromCode}-${t.toCode}`} t={t} />
          ))}
        </ol>
      </section>

      <section>
        <h2 className="text-lg font-semibold">{yearSpan} 5년 추이</h2>
        <p className="mb-3 text-sm text-muted-foreground">
          매년 6월 기준 전국 점포 수. 지금 {MIN_SMALL_FOR_TREND}곳 이상인 소분류만. 2023~2024년은 원본 수집 범위가 줄었다 회복한 흔적이 있어 증감폭을 그대로 믿기보다 방향만 보세요.
        </p>
        <div className="grid gap-6 lg:grid-cols-2">
          <TrendList title="뜨는 업종" rows={rising} />
          <TrendList title="지는 업종" rows={falling} />
        </div>
      </section>

      <section>
        <h2 className="text-lg font-semibold">브랜드 출점과 폐점</h2>
        <p className="mb-3 text-sm text-muted-foreground">
          상호명이 같은 가게를 묶어 셌습니다. 프랜차이즈 공식 집계가 아니라 간판 기준이라 오차가 있고, 지역명이 상호에 붙은 브랜드(메가커피 등)는 쪼개져 빠집니다. 1년 새 표기 방식이 바뀐 브랜드는 뺐습니다.
        </p>
        <div className="grid gap-6 lg:grid-cols-2">
          <BrandList title="가장 많이 늘어난 브랜드" rows={brandUp} />
          <BrandList title="가장 많이 줄어든 브랜드" rows={brandDown} />
        </div>
      </section>

      <section>
        <h2 className="text-lg font-semibold">가장 많이 바뀐 동네</h2>
        <p className="mb-3 text-sm text-muted-foreground">
          교체율 = (신규+소멸) ÷ 1년 전 상가 수. 상가 {MIN_REGION_STORES.toLocaleString()}곳 이상인 시군구만.
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
                <ArrowRight className="size-4 text-muted-foreground" aria-hidden />
              </Link>
            </li>
          ))}
        </ol>
      </section>

      <p className="rounded-xl bg-[#F9FAFB] p-4 text-xs text-muted-foreground">
        신규·소멸·전환·브랜드는 원본에 있는 값이 아니라 두 분기 목록을 상가업소번호와 주소로 맞춰 본 추정입니다. 전국
        {' '}{opened.toLocaleString()}곳 신규, {closed.toLocaleString()}곳 소멸.
      </p>
    </div>
  );
}

function Headline({ kicker, value, detail, tone }: { kicker: string; value: string; detail: string; tone?: 'up' | 'down' }) {
  const color = tone === 'up' ? 'text-primary' : tone === 'down' ? 'text-[#E5484D]' : '';
  return (
    <div className="rounded-2xl border border-[#E5E8EB] bg-white p-4">
      <div className="text-xs text-muted-foreground">{kicker}</div>
      <div className={`mt-1 text-xl font-bold ${color}`}>{value}</div>
      <div className="mt-1 text-xs text-muted-foreground">{detail}</div>
    </div>
  );
}

function RateList({ title, rows, baseline }: { title: string; rows: UpjongStat[]; baseline: number }) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-muted-foreground">{title}</h3>
      <ol className="divide-y rounded-2xl border border-[#E5E8EB] bg-white">
        {rows.map((u) => (
          <li key={u.code}>
            <Link href={`/u/${u.code}`} className="block p-3 hover:bg-accent">
              <div className="flex items-center gap-3">
                <span className="flex-1 text-sm">{u.name}</span>
                <span className="text-sm font-semibold tabular-nums">{pct(u.closeRate)}</span>
                <span className="w-20 text-right text-xs text-muted-foreground tabular-nums">{u.stores.toLocaleString()}곳</span>
              </div>
              <div className="mt-1.5">
                <RateBar value={u.closeRate} baseline={baseline} />
              </div>
            </Link>
          </li>
        ))}
      </ol>
    </div>
  );
}

function TransitionRow({ t }: { t: Transition }) {
  return (
    <li className="flex items-center gap-3 p-3">
      <span className="flex-1 text-sm">
        <span className="text-[#E5484D]">{t.fromName}</span> <ArrowRight className="inline size-3.5 text-muted-foreground" aria-hidden />{' '}
        <span className="text-primary">{t.toName}</span>
      </span>
      <span className="text-sm font-semibold tabular-nums">{t.count.toLocaleString()}곳</span>
    </li>
  );
}

function TrendList({ title, rows }: { title: string; rows: (SmallUpjongStat & { series: number[]; growth: number })[] }) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-muted-foreground">{title}</h3>
      <ol className="divide-y rounded-2xl border border-[#E5E8EB] bg-white">
        {rows.map((s) => (
          <li key={s.code} className="flex items-center gap-3 p-3">
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm">{s.name}</div>
              <div className="text-xs text-muted-foreground">{s.middleName}</div>
            </div>
            <Sparkline values={s.series} color={s.growth >= 0 ? '#3182F6' : '#E5484D'} />
            <span className={`w-16 text-right text-sm font-semibold tabular-nums ${s.growth >= 0 ? 'text-primary' : 'text-[#E5484D]'}`}>
              {s.growth >= 0 ? '+' : ''}
              {(s.growth * 100).toFixed(0)}%
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function BrandList({ title, rows }: { title: string; rows: BrandStat[] }) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-muted-foreground">{title}</h3>
      <ol className="divide-y rounded-2xl border border-[#E5E8EB] bg-white">
        {rows.map((b) => {
          const d = b.stores - b.prevStores;
          return (
            <li key={b.name} className="flex items-center gap-3 p-3">
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm">{b.name}</div>
                <div className="text-xs text-muted-foreground">{b.upjong}</div>
              </div>
              <span className={`text-sm font-semibold tabular-nums ${d >= 0 ? 'text-primary' : 'text-[#E5484D]'}`}>{signed(d)}</span>
              <span className="w-20 text-right text-xs text-muted-foreground tabular-nums">{b.stores.toLocaleString()}곳</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
