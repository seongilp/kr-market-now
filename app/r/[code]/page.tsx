import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';

import { Stat } from '@/components/stat';
import { changes, dongList, getSigungu, meta, pct, quarterLabel, sigunguList, signed } from '@/lib/data';
import type { ChangeItem, DongSummary } from '@/lib/data-types';

const CHANGE_LIMIT = 60;

export function generateStaticParams() {
  return sigunguList.map((r) => ({ code: r.code }));
}

export async function generateMetadata({ params }: PageProps<'/r/[code]'>): Promise<Metadata> {
  const r = getSigungu((await params).code);
  return r ? { title: `${r.sido} ${r.name} 상권`, description: `${r.name}에서 1년 사이 생긴 가게와 사라진 가게` } : {};
}

export default async function RegionPage({ params }: PageProps<'/r/[code]'>) {
  const { code } = await params;
  const region = getSigungu(code);
  if (!region) notFound();

  const [dongs, change] = await Promise.all([dongList(code), changes(code)]);
  const byStores = [...dongs].sort((a, b) => b.stores - a.stores);
  const nationalRate = (meta.totals.opened + meta.totals.closed) / meta.totals.prevStores;

  return (
    <div className="space-y-8">
      <nav className="text-sm text-muted-foreground">
        <Link href="/" className="hover:text-foreground">
          홈
        </Link>{' '}
        / {region.sido}
      </nav>

      <header className="space-y-1">
        <h1 className="text-2xl font-bold">
          {region.sido} {region.name}
        </h1>
        <p className="text-sm text-muted-foreground">
          {quarterLabel(meta.previous)} → {quarterLabel(meta.current)} 비교
        </p>
      </header>

      <section className="grid gap-3 sm:grid-cols-4">
        <Stat label="상가" value={region.stores.toLocaleString()} sub={`1년 전 ${region.prevStores.toLocaleString()}곳`} />
        <Stat label="새로 생긴 곳" value={region.opened.toLocaleString()} tone="up" />
        <Stat label="사라진 곳" value={region.closed.toLocaleString()} tone="down" />
        <Stat label="교체율" value={pct(region.turnoverRate)} sub={`전국 평균 ${pct(nationalRate)}`} />
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
        <ChangeList
          title="새로 생긴 가게"
          note={`${change.openedTotal.toLocaleString()}곳 중 ${Math.min(CHANGE_LIMIT, change.opened.length)}곳`}
          items={change.opened.slice(0, CHANGE_LIMIT)}
          tone="up"
        />
        <ChangeList
          title="사라진 가게"
          note={`${change.closedTotal.toLocaleString()}곳 중 ${Math.min(CHANGE_LIMIT, change.closed.length)}곳`}
          items={change.closed.slice(0, CHANGE_LIMIT)}
          tone="down"
        />
      </section>

      <p className="rounded-xl bg-[#F9FAFB] p-4 text-xs text-muted-foreground">
        신규·소멸은 원본 데이터에 있는 값이 아닙니다. 두 분기 목록을 상가업소번호로 맞춰 본 결과라, 폐업이 아니라 정보
        정비로 번호가 바뀐 경우도 섞일 수 있습니다.
      </p>
    </div>
  );
}

function DongRow({ dong }: { dong: DongSummary }) {
  const delta = dong.stores - dong.prevStores;
  return (
    <tr className="hover:bg-accent/40">
      <td className="px-3 py-2 whitespace-nowrap">{dong.name}</td>
      <td className="px-3 py-2 text-right tabular-nums">{dong.stores.toLocaleString()}</td>
      <td className={`px-3 py-2 text-right tabular-nums ${delta >= 0 ? 'text-primary' : 'text-[#E5484D]'}`}>
        {signed(delta)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">{dong.opened.toLocaleString()}</td>
      <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">{dong.closed.toLocaleString()}</td>
      <td className="px-3 py-2 text-right tabular-nums">{pct(dong.turnoverRate)}</td>
      <td className="hidden px-3 py-2 text-muted-foreground sm:table-cell">
        {dong.top
          .slice(0, 3)
          .map((t) => t.name)
          .join(' · ')}
      </td>
    </tr>
  );
}

function ChangeList({
  title,
  note,
  items,
  tone,
}: {
  title: string;
  note: string;
  items: ChangeItem[];
  tone: 'up' | 'down';
}) {
  return (
    <div>
      <h2 className="mb-1 text-lg font-semibold">{title}</h2>
      <p className="mb-3 text-sm text-muted-foreground">{note}</p>
      <ul className="divide-y rounded-2xl border border-[#E5E8EB] bg-white">
        {items.length === 0 && <li className="p-3 text-sm text-muted-foreground">해당하는 가게가 없습니다.</li>}
        {items.map((it, i) => (
          <li key={`${it.name}-${i}`} className="p-3">
            <div className="flex items-baseline gap-2">
              <span className={`text-sm font-medium ${tone === 'up' ? 'text-primary' : 'text-[#E5484D]'}`}>
                {tone === 'up' ? '신규' : '소멸'}
              </span>
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
