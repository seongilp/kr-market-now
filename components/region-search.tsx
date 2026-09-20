'use client';

import Link from 'next/link';
import { useDeferredValue, useMemo, useState } from 'react';
import { Search } from 'lucide-react';

import { Input } from '@/components/ui/input';
import type { SigunguSummary } from '@/lib/data-types';

const MAX_RESULTS = 20;

export function RegionSearch({ regions }: { regions: SigunguSummary[] }) {
  const [q, setQ] = useState('');
  const deferred = useDeferredValue(q);

  const hits = useMemo(() => {
    const terms = deferred.trim().split(/\s+/).filter(Boolean);
    if (terms.length === 0) return [];
    return regions
      .filter((r) => terms.every((t) => `${r.sido} ${r.name}`.includes(t)))
      .slice(0, MAX_RESULTS);
  }, [deferred, regions]);

  return (
    <div>
      {/* 아이콘은 입력창만 감싼 래퍼 기준으로 세로 중앙에 둔다 — 결과 목록까지 감싸면 아래로 밀린다 */}
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="동네 찾기 — 예: 강남구, 수지구, 전주"
          className="h-12 rounded-xl border-[#E5E8EB] bg-white pl-9 text-base shadow-sm focus-visible:border-primary"
          aria-label="시군구 검색"
        />
      </div>
      {deferred.trim() && (
        <ul className="mt-2 divide-y rounded-xl border bg-white">
          {hits.length === 0 && <li className="p-3 text-sm text-muted-foreground">그런 지역이 없어요.</li>}
          {hits.map((r) => (
            <li key={r.code}>
              <Link href={`/r/${r.code}`} className="flex items-center justify-between gap-3 p-3 hover:bg-accent">
                <span className="text-sm">
                  {r.sido} <strong>{r.name}</strong>
                </span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {r.stores.toLocaleString()}곳 · 교체율 {(r.turnoverRate * 100).toFixed(1)}%
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
