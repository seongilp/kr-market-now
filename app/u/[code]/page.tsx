import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';

import { upjong, upjongRank } from '@/lib/data';

/** rank 파일은 전국 점포 수 상위 30개 업종만 있다 */
const RANKED = new Set(
  [...upjong.middle]
    .sort((a, b) => b.stores - a.stores)
    .slice(0, 30)
    .map((u) => u.code),
);

export function generateStaticParams() {
  return [...RANKED].map((code) => ({ code }));
}

export async function generateMetadata({ params }: PageProps<'/u/[code]'>): Promise<Metadata> {
  const { code } = await params;
  const row = upjong.middle.find((u) => u.code === code);
  return row ? { title: `${row.name}이 많은 동네` } : {};
}

export default async function UpjongPage({ params }: PageProps<'/u/[code]'>) {
  const { code } = await params;
  if (!RANKED.has(code)) notFound();
  const rank = await upjongRank(code);

  return (
    <div className="space-y-6">
      <nav className="text-sm text-muted-foreground">
        <Link href="/" className="hover:text-foreground">
          홈
        </Link>{' '}
        / 업종
      </nav>
      <h1 className="text-2xl font-bold">{rank.name}이 많은 동네</h1>
      <ol className="divide-y rounded-2xl border border-[#E5E8EB] bg-white">
        {rank.rows.map((r, i) => (
          <li key={r.sigunguCode}>
            <Link href={`/r/${r.sigunguCode}`} className="flex items-center gap-3 p-3 hover:bg-accent">
              <span className="w-5 text-center text-sm text-muted-foreground tabular-nums">{i + 1}</span>
              <span className="flex-1 text-sm">
                {r.sido} <strong>{r.name}</strong>
              </span>
              <span className="text-sm font-semibold tabular-nums">{r.stores.toLocaleString()}곳</span>
            </Link>
          </li>
        ))}
      </ol>
    </div>
  );
}
