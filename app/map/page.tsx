import type { Metadata } from 'next';
import Link from 'next/link';

import { NationalMap } from '@/components/national-map';
import dotsJson from '@/data/dots.json';
import { meta, quarterLabel } from '@/lib/data';
import type { Dot } from '@/lib/data-types';

export const metadata: Metadata = {
  title: '전국 지도',
  description: '1년 사이 새로 생긴 가게는 파란 점, 사라진 가게는 빨간 점으로 전국 지도에 표시합니다.',
};

export default function MapPage() {
  const dots = dotsJson as Dot[];
  const { opened, closed } = meta.totals;

  return (
    <div className="space-y-4">
      <nav className="text-sm text-muted-foreground">
        <Link href="/" className="hover:text-foreground">
          홈
        </Link>{' '}
        / 전국 지도
      </nav>
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">전국 지도</h1>
        <p className="text-sm text-muted-foreground">
          {quarterLabel(meta.previous)} → {quarterLabel(meta.current)} 사이 신규 {opened.toLocaleString()}곳, 소멸{' '}
          {closed.toLocaleString()}곳. 넓게 볼 때는 행정동 {dots.length.toLocaleString()}개를 원 하나로 묶어 보여주고,
          확대하면 가게 하나하나가 점으로 나옵니다.
        </p>
      </header>
      <NationalMap dots={dots} />
      <p className="rounded-xl bg-[#F9FAFB] p-4 text-xs text-muted-foreground">
        개별 점은 용량 때문에 지역마다 일부만 추려 담았습니다. 동네 원의 신규·소멸 숫자는 전수 집계입니다.
      </p>
    </div>
  );
}
