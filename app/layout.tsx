import type { Metadata, Viewport } from 'next';
import Link from 'next/link';
import { Store } from 'lucide-react';

import 'pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css';
import './globals.css';

const NAME = '상권나우';
const TITLE = `${NAME} — 우리 동네 상권, 숫자로 보기`;
const DESCRIPTION =
  '전국 상가 277만 곳의 업종 구성과 밀도, 분기별 변화를 동네 단위로 분석합니다. 소상공인시장진흥공단 상가(상권)정보 기반.';

export const metadata: Metadata = {
  metadataBase: new URL('https://kr-market-now.vercel.app'),
  title: { default: TITLE, template: `%s — ${NAME}` },
  description: DESCRIPTION,
  applicationName: NAME,
  openGraph: { title: TITLE, description: DESCRIPTION, siteName: NAME, type: 'website', locale: 'ko_KR' },
};

export const viewport: Viewport = {
  themeColor: '#ffffff',
  colorScheme: 'light',
};

export default function RootLayout({ children }: LayoutProps<'/'>) {
  return (
    <html lang="ko" className="h-full antialiased">
      <body className="flex min-h-full flex-col bg-white font-sans text-[#191F28]">
        <header className="sticky top-0 z-20 border-b border-[#F2F4F6] bg-white/90 backdrop-blur">
          <div className="mx-auto flex h-14 max-w-6xl items-center gap-2 px-4">
            <Link href="/" className="flex items-center gap-2 font-semibold">
              <span className="grid size-7 place-items-center rounded-lg bg-primary text-white">
                <Store className="size-4" aria-hidden />
              </span>
              {NAME}
            </Link>
            <nav className="ml-auto text-sm">
              <Link href="/map" className="text-muted-foreground hover:text-foreground">
                전국 지도
              </Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
        <footer className="border-t border-[#F2F4F6] bg-[#F9FAFB] py-6 text-center text-xs text-muted-foreground">
          데이터 출처: 소상공인시장진흥공단 상가(상권)정보 (공공데이터포털). 분기 스냅샷 기준이라 실제와 다를 수 있습니다.
          <br />
          <a className="underline underline-offset-2" href="https://github.com/seongilp/kr-market-now">
            GitHub
          </a>
        </footer>
      </body>
    </html>
  );
}
