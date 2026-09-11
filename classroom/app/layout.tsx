import type { Metadata } from "next";
import { IBM_Plex_Mono } from "next/font/google";
import Link from "next/link";
import localFont from "next/font/local";
import type { ReactNode } from "react";

import "./globals.css";

// 서체는 공개 앱과 같다 (#298) — 두 서브도메인이 한 제품이므로 글꼴이 갈리면
// 사람이 먼저 알아챈다. 파일도 `app/fonts/` 에 같은 것을 담는다(공유 패키지로
// 빼지 않은 이유와, 갈라지지 않게 지키는 방법은 `lib/design/tokens.test.ts`).
//
// Pretendard 는 Google Fonts 에 없어 `next/font/local` 로 셀프호스팅한다. 폴백
// 스택의 최종 결정은 `app/tokens.css` 의 `--font-sans`/`--font-mono` 이고, 여기서는
// 변수만 채운다.
const pretendard = localFont({
  src: "./fonts/PretendardVariable.woff2",
  weight: "45 920",
  variable: "--font-pretendard",
  display: "swap",
});

const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-ibm-plex-mono",
  display: "swap",
});

// 색인 대상이 아니다(ADR-0015·ADR-0021/0037과 같은 원칙 — 운영자 앱
// operator/app/layout.tsx 참고). 이 앱의 독자는 로그인한 참여자·강사뿐이다.
export const metadata: Metadata = {
  title: "Laurio 강의실",
  robots: { index: false, follow: false },
};

// "/" 로 가는 링크가 최소 하나 있어야 고아 라우트 검사(lib/routes/orphan-routes.test.ts,
// #166)가 홈을 고아로 잡지 않는다 — 공개 앱의 SiteHeader(app/components/site-header.tsx)와
// 같은 자리다.
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko" className={`${pretendard.variable} ${ibmPlexMono.variable}`}>
      <body>
        <header className="border-b border-rule bg-surface">
          <div className="mx-auto flex h-[72px] max-w-[1200px] items-center px-6">
            <Link
              href="/"
              data-testid="classroom-header-brand"
              className="text-[21px] font-bold tracking-[-0.01em] text-ink"
            >
              Laurio <span className="text-[15px] font-normal text-ink/45">강의실</span>
            </Link>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
