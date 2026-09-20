import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { ArrowRight } from 'lucide-react';

import { ChangeMap } from '@/components/change-map';
import { RateBar } from '@/components/rate-bar';
import { Stat } from '@/components/stat';
import { UpjongCheck } from '@/components/upjong-check';
import { changes, dongList, getSigungu, meta, pct, quarterLabel, regionCenter, sigunguList, signed } from '@/lib/data';
import type { ChangeItem, DongSummary } from '@/lib/data-types';
import { regionType, specialization } from '@/lib/diagnose';
import { national, realBrands, regionInsights, sumStores } from '@/lib/insights';
import type { BrandStat, MiddleUpjongStat, TransitionExample } from '@/lib/insight-types';

const CHANGE_LIMIT = 40;
const MIN_UPJONG_STORES = 30;
const TOP = 6;

export function generateStaticParams() {
  return sigunguList.map((r) => ({ code: r.code }));
}

export async function generateMetadata({ params }: PageProps<'/r/[code]'>): Promise<Metadata> {
  const r = getSigungu((await params).code);
  return r ? { title: `${r.sido} ${r.name} 상권 진단`, description: `${r.name}에서 무엇이 살아남고 무엇이 사라지는지` } : {};
}

export default async function RegionPage({ params }: PageProps<'/r/[code]'>) {
  const { code } = await params;
  const region = getSigungu(code);
  if (!region) notFound();

  const [dongs, change, ins] = await Promise.all([dongList(code), changes(code), regionInsights(code)]);
  const nationalTotals = {
    stores: meta.totals.stores,
    prevStores: meta.totals.prevStores,
    turnoverRate: (meta.totals.opened + meta.totals.closed) / meta.totals.prevStores,
  };
  const nationalClose = meta.totals.closed / meta.totals.prevStores;
  const nationalGrowthPct = ((nationalTotals.stores / nationalTotals.prevStores - 1) * 100).toFixed(1);
  const diag = regionType(region, nationalTotals);

  const regionTotal = sumStores(ins.middle);
  const nationalTotal = sumStores(national.middle);
  const natByCode = new Map(national.middle.map((m) => [m.code, m]));

  const enough = ins.middle.filter((m) => m.prevStores >= MIN_UPJONG_STORES);
  const specialized = enough
    .map((m) => ({ m, lq: specialization(m, regionTotal, natByCode.get(m.code) ?? m, nationalTotal) }))
    .sort((a, b) => b.lq - a.lq)
    .slice(0, TOP);
  const risky = enough
    .map((m) => ({ m, gap: m.closeRate - (natByCode.get(m.code)?.closeRate ?? nationalClose) }))
    .filter((x) => x.gap > 0)
    .sort((a, b) => b.gap - a.gap)
    .slice(0, TOP);
  const growing = enough
    .map((m) => ({ m, net: m.opened - m.closed, gap: m.openRate - (natByCode.get(m.code)?.openRate ?? 0) }))
    .sort((a, b) => b.gap - a.gap)
    .slice(0, TOP);

  const switches = ins.transitions.filter((t) => t.fromCode !== t.toCode).slice(0, 8);
  const brandsOk = realBrands(ins.brands);
  const brandUp = [...brandsOk].sort((a, b) => b.stores - b.prevStores - (a.stores - a.prevStores)).filter((b) => b.stores > b.prevStores).slice(0, 5);
  const brandDown = [...brandsOk].sort((a, b) => a.stores - a.prevStores - (b.stores - b.prevStores)).filter((b) => b.stores < b.prevStores).slice(0, 5);
  const byStores = [...dongs].sort((a, b) => b.stores - a.stores);
  const center = regionCenter(code);

  return (
    <div className="space-y-10">
      <nav className="text-sm text-muted-foreground">
        <Link href="/" className="hover:text-foreground">
          홈
        </Link>{' '}
        / {region.sido}
      </nav>

      <header className="space-y-3">
        <h1 className="text-2xl font-bold">
          {region.sido} {region.name}
        </h1>
        <div className="rounded-2xl border border-primary/30 bg-[var(--brand-soft)] p-4">
          <div className="text-xs font-medium text-primary">진단</div>
          <div className="text-lg font-bold">{diag.label}</div>
          <p className="mt-1 text-sm text-muted-foreground">
            {diag.description} 1년 사이 상가 {signed(region.stores - region.prevStores)}곳(전국 +{nationalGrowthPct}%), 교체율{' '}
            {pct(region.turnoverRate)}(전국 {pct(nationalTotals.turnoverRate)}).
          </p>
        </div>
      </header>

      <section className="grid gap-3 sm:grid-cols-4">
        <Stat label="상가" value={region.stores.toLocaleString()} sub={`1년 전 ${region.prevStores.toLocaleString()}곳`} />
        <Stat label="새로 생긴 곳" value={region.opened.toLocaleString()} tone="up" />
        <Stat label="사라진 곳" value={region.closed.toLocaleString()} tone="down" />
        <Stat label="1년 소멸률" value={pct(region.closed / region.prevStores)} sub={`전국 ${pct(nationalClose)}`} />
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">여기서 이 업종 해도 될까</h2>
        <UpjongCheck regionName={region.name} region={ins.middle} regionTotal={regionTotal} national={national.middle} nationalTotal={nationalTotal} />
      </section>

      <section className="grid gap-6 lg:grid-cols-3">
        <div>
          <h2 className="text-lg font-semibold">이 동네에 유독 많은 업종</h2>
          <p className="mb-3 text-sm text-muted-foreground">전국 비중 대비 몇 배인지</p>
          <ul className="divide-y rounded-2xl border border-[#E5E8EB] bg-white">
            {specialized.map(({ m, lq }) => (
              <UpjongRow key={m.code} m={m} right={`${lq.toFixed(1)}배`} sub={`${m.stores.toLocaleString()}곳`} />
            ))}
          </ul>
        </div>
        <div>
          <h2 className="text-lg font-semibold">전국보다 빨리 늘어난 업종</h2>
          <p className="mb-3 text-sm text-muted-foreground">1년 신규 비율이 전국보다 높은 순</p>
          <ul className="divide-y rounded-2xl border border-[#E5E8EB] bg-white">
            {growing.map(({ m, net }) => (
              <UpjongRow key={m.code} m={m} right={signed(net)} sub={`신규 ${m.opened} · 소멸 ${m.closed}`} tone={net >= 0 ? 'up' : 'down'} />
            ))}
          </ul>
        </div>
        <div>
          <h2 className="text-lg font-semibold">전국보다 자주 사라진 업종</h2>
          <p className="mb-3 text-sm text-muted-foreground">1년 소멸률, 선은 전국 평균</p>
          <ul className="divide-y rounded-2xl border border-[#E5E8EB] bg-white">
            {risky.length === 0 && <li className="p-3 text-sm text-muted-foreground">전국보다 높은 업종이 없습니다.</li>}
            {risky.map(({ m }) => (
              <li key={m.code} className="p-3">
                <div className="flex items-center gap-3">
                  <span className="flex-1 text-sm">{m.name}</span>
                  <span className="text-sm font-semibold tabular-nums text-[#E5484D]">{pct(m.closeRate)}</span>
                  <span className="text-xs text-muted-foreground tabular-nums">전국 {pct(natByCode.get(m.code)?.closeRate ?? 0)}</span>
                </div>
                <div className="mt-1.5">
                  <RateBar value={m.closeRate} baseline={natByCode.get(m.code)?.closeRate ?? nationalClose} />
                </div>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div>
          <h2 className="text-lg font-semibold">사라진 자리에 들어온 업종</h2>
          <p className="mb-3 text-sm text-muted-foreground">같은 주소·층·호로 이어 붙인 업종 전환</p>
          <ol className="divide-y rounded-2xl border border-[#E5E8EB] bg-white">
            {switches.length === 0 && <li className="p-3 text-sm text-muted-foreground">이어 붙일 수 있는 자리가 적습니다.</li>}
            {switches.map((t) => (
              <li key={`${t.fromCode}-${t.toCode}`} className="flex items-center gap-3 p-3">
                <span className="flex-1 text-sm">
                  <span className="text-[#E5484D]">{t.fromName}</span> <ArrowRight className="inline size-3.5 text-muted-foreground" aria-hidden />{' '}
                  <span className="text-primary">{t.toName}</span>
                </span>
                <span className="text-sm font-semibold tabular-nums">{t.count}곳</span>
              </li>
            ))}
          </ol>
        </div>
        <div>
          <h2 className="text-lg font-semibold">실제 사례</h2>
          <p className="mb-3 text-sm text-muted-foreground">이 자리에 원래 뭐가 있었나</p>
          <ul className="divide-y rounded-2xl border border-[#E5E8EB] bg-white">
            {ins.transitionExamples.length === 0 && <li className="p-3 text-sm text-muted-foreground">사례가 없습니다.</li>}
            {ins.transitionExamples.slice(0, 10).map((ex, i) => (
              <ExampleRow key={i} ex={ex} />
            ))}
          </ul>
        </div>
      </section>

      {(brandUp.length > 0 || brandDown.length > 0) && (
        <section className="grid gap-6 lg:grid-cols-2">
          <BrandList title="늘어난 브랜드" rows={brandUp} />
          <BrandList title="줄어든 브랜드" rows={brandDown} />
        </section>
      )}

      <section>
        <h2 className="mb-1 text-lg font-semibold">지도에서 보기</h2>
        <p className="mb-3 text-sm text-muted-foreground">파란 점이 새로 생긴 곳, 빨간 점이 사라진 곳. 점을 누르면 상호와 업종이 나옵니다.</p>
        <ChangeMap code={region.code} regionName={region.name} />
        {center && (
          <Link
            href={`/map?lat=${center.lat}&lng=${center.lon}&z=12.5`}
            className="mt-2 inline-block text-sm font-medium text-primary hover:underline"
          >
            전국 지도에서 이 동네 보기 →
          </Link>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">동네별로 보기</h2>
        <div className="overflow-x-auto rounded-2xl border border-[#E5E8EB] bg-white">
          <table className="w-full text-sm">
            <thead className="bg-muted/60 text-left">
              <tr>
                <th className="px-3 py-2 font-medium">행정동</th>
                <th className="px-3 py-2 text-right font-medium">상가</th>
                <th className="px-3 py-2 text-right font-medium">증감</th>
                <th className="px-3 py-2 text-right font-medium">신규</th>
                <th className="px-3 py-2 text-right font-medium">소멸</th>
                <th className="px-3 py-2 text-right font-medium">교체율</th>
                <th className="hidden px-3 py-2 font-medium sm:table-cell">많은 업종</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {byStores.map((d) => (
                <DongRow key={d.code} dong={d} />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <ChangeList title="새로 생긴 가게" note={`${change.openedTotal.toLocaleString()}곳 중 ${Math.min(CHANGE_LIMIT, change.opened.length)}곳`} items={change.opened.slice(0, CHANGE_LIMIT)} tone="up" />
        <ChangeList title="사라진 가게" note={`${change.closedTotal.toLocaleString()}곳 중 ${Math.min(CHANGE_LIMIT, change.closed.length)}곳`} items={change.closed.slice(0, CHANGE_LIMIT)} tone="down" />
      </section>

      <p className="rounded-xl bg-[#F9FAFB] p-4 text-xs text-muted-foreground">
        신규·소멸·전환·브랜드는 원본에 있는 값이 아닙니다. {quarterLabel(meta.previous)}과 {quarterLabel(meta.current)} 두 목록을
        상가업소번호와 주소로 맞춰 본 추정이라, 폐업이 아니라 정보 정비로 번호가 바뀐 경우도 섞일 수 있습니다.
      </p>
    </div>
  );
}

function UpjongRow({ m, right, sub, tone }: { m: MiddleUpjongStat; right: string; sub: string; tone?: 'up' | 'down' }) {
  const color = tone === 'up' ? 'text-primary' : tone === 'down' ? 'text-[#E5484D]' : '';
  return (
    <li>
      <Link href={`/u/${m.code}`} className="flex items-center gap-3 p-3 hover:bg-accent">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm">{m.name}</div>
          <div className="text-xs text-muted-foreground">{sub}</div>
        </div>
        <span className={`text-sm font-semibold tabular-nums ${color}`}>{right}</span>
      </Link>
    </li>
  );
}

function ExampleRow({ ex }: { ex: TransitionExample }) {
  return (
    <li className="p-3">
      <div className="text-sm">
        <span className="text-[#E5484D]">{ex.fromName}</span>
        <span className="text-xs text-muted-foreground"> ({ex.fromUpjong})</span>{' '}
        <ArrowRight className="inline size-3.5 text-muted-foreground" aria-hidden /> <span className="text-primary">{ex.toName}</span>
        <span className="text-xs text-muted-foreground"> ({ex.toUpjong})</span>
      </div>
      <div className="mt-0.5 text-xs text-muted-foreground">
        {ex.dong} · {ex.road}
      </div>
    </li>
  );
}

function BrandList({ title, rows }: { title: string; rows: BrandStat[] }) {
  return (
    <div>
      <h2 className="mb-3 text-lg font-semibold">{title}</h2>
      <ul className="divide-y rounded-2xl border border-[#E5E8EB] bg-white">
        {rows.length === 0 && <li className="p-3 text-sm text-muted-foreground">해당 없음</li>}
        {rows.map((b) => {
          const d = b.stores - b.prevStores;
          return (
            <li key={b.name} className="flex items-center gap-3 p-3">
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm">{b.name}</div>
                <div className="text-xs text-muted-foreground">{b.upjong}</div>
              </div>
              <span className={`text-sm font-semibold tabular-nums ${d >= 0 ? 'text-primary' : 'text-[#E5484D]'}`}>{signed(d)}</span>
              <span className="w-16 text-right text-xs text-muted-foreground tabular-nums">{b.stores}곳</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function DongRow({ dong }: { dong: DongSummary }) {
  const delta = dong.stores - dong.prevStores;
  return (
    <tr className="hover:bg-accent/40">
      <td className="px-3 py-2 whitespace-nowrap">{dong.name}</td>
      <td className="px-3 py-2 text-right tabular-nums">{dong.stores.toLocaleString()}</td>
      <td className={`px-3 py-2 text-right tabular-nums ${delta >= 0 ? 'text-primary' : 'text-[#E5484D]'}`}>{signed(delta)}</td>
      <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">{dong.opened.toLocaleString()}</td>
      <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">{dong.closed.toLocaleString()}</td>
      <td className="px-3 py-2 text-right tabular-nums">{pct(dong.turnoverRate)}</td>
      <td className="hidden px-3 py-2 text-muted-foreground sm:table-cell">{dong.top.slice(0, 3).map((t) => t.name).join(' · ')}</td>
    </tr>
  );
}

function ChangeList({ title, note, items, tone }: { title: string; note: string; items: ChangeItem[]; tone: 'up' | 'down' }) {
  return (
    <div>
      <h2 className="mb-1 text-lg font-semibold">{title}</h2>
      <p className="mb-3 text-sm text-muted-foreground">{note}</p>
      <ul className="divide-y rounded-2xl border border-[#E5E8EB] bg-white">
        {items.map((it, i) => (
          <li key={`${it.name}-${i}`} className="p-3">
            <div className="flex items-baseline gap-2">
              <span className={`text-sm font-medium ${tone === 'up' ? 'text-primary' : 'text-[#E5484D]'}`}>{tone === 'up' ? '신규' : '소멸'}</span>
              <span className="text-sm">
                {it.name}
                {it.branch ? ` ${it.branch}` : ''}
              </span>
            </div>
            <div className="mt-0.5 text-xs text-muted-foreground">
              {it.upjong} · {it.dong} · {it.road}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
