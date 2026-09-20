'use client';

import { useMemo, useState } from 'react';
import { CircleAlert, CircleCheck, TriangleAlert } from 'lucide-react';

import { RateBar } from '@/components/rate-bar';
import { checkUpjong, type Verdict } from '@/lib/diagnose';
import type { MiddleUpjongStat } from '@/lib/insight-types';

const ICON: Record<Verdict, typeof CircleCheck> = { good: CircleCheck, caution: CircleAlert, risky: TriangleAlert };
const TONE: Record<Verdict, string> = {
  good: 'border-primary/30 bg-[var(--brand-soft)] text-primary',
  caution: 'border-[#F5A524]/40 bg-[#FFF8E6] text-[#B26B00]',
  risky: 'border-[#E5484D]/40 bg-[#FFF1F2] text-[#C81E1E]',
};

/** 동네 + 업종을 고르면 "여기서 이 업종 해도 되나"를 판정한다 */
export function UpjongCheck({
  regionName,
  region,
  regionTotal,
  national,
  nationalTotal,
}: {
  regionName: string;
  region: MiddleUpjongStat[];
  regionTotal: number;
  national: MiddleUpjongStat[];
  nationalTotal: number;
}) {
  const options = useMemo(() => [...national].sort((a, b) => b.stores - a.stores), [national]);
  const [code, setCode] = useState(options[0]?.code ?? '');

  const nat = national.find((n) => n.code === code);
  const reg = region.find((r) => r.code === code) ?? (nat ? { ...nat, stores: 0, prevStores: 0, opened: 0, closed: 0, closeRate: 0, openRate: 0 } : undefined);
  const result = nat && reg ? checkUpjong(reg, regionTotal, nat, nationalTotal) : undefined;
  const Icon = result ? ICON[result.verdict] : CircleCheck;

  return (
    <div className="rounded-2xl border border-[#E5E8EB] bg-white p-4">
      <label className="block text-sm text-muted-foreground">
        {regionName}에서 이 업종을 한다면
        <select
          value={code}
          onChange={(e) => setCode(e.target.value)}
          className="mt-1 block h-11 w-full rounded-xl border border-[#E5E8EB] bg-white px-3 text-base text-foreground focus-visible:border-primary focus-visible:outline-none"
        >
          {options.map((o) => (
            <option key={o.code} value={o.code}>
              {o.name}
            </option>
          ))}
        </select>
      </label>

      {result && reg && nat && (
        <div className="mt-4 space-y-3">
          <div className={`flex items-center gap-2 rounded-xl border px-3 py-2 font-semibold ${TONE[result.verdict]}`}>
            <Icon className="size-5" aria-hidden />
            {result.label}
          </div>
          <ul className="space-y-1 text-sm">
            {result.reasons.map((r) => (
              <li key={r}>· {r}</li>
            ))}
          </ul>
          <div className="grid gap-3 sm:grid-cols-3">
            <Metric label={`${regionName} ${nat.name}`} value={`${reg.stores.toLocaleString()}곳`} sub={`1년 전 ${reg.prevStores.toLocaleString()}곳`} />
            <div>
              <div className="text-xs text-muted-foreground">1년 소멸률 (선은 전국)</div>
              <div className="mb-1 text-lg font-bold tabular-nums">{(result.closeRate * 100).toFixed(1)}%</div>
              <RateBar value={result.closeRate} baseline={result.nationalCloseRate} />
            </div>
            <Metric label="특화 지수" value={`${result.lq.toFixed(2)}배`} sub="1.0 = 전국과 같은 비중" />
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-bold tabular-nums">{value}</div>
      {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}
