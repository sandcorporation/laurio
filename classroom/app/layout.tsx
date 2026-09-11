import type { Metadata } from "next";
import { IBM_Plex_Mono } from "next/font/google";
import Link from "next/link";
import localFont from "next/font/local";
import type { ReactNode } from "react";

import { AccountMenu } from "./components/account-menu";
import { NotificationBell } from "./components/notification-bell";

import "./globals.css";

// **정적으로 구워지면 안 된다** (#297, lib/rendering/runtime-config.test.ts).
// `AccountMenu`가 이 레이아웃 트리에서 `headers()`와 `LAURIO_WEB_ORIGIN`·
// `LAURIO_CLASSROOM_ORIGIN`을 읽는다 — 그 값이 빌드 머신 것으로 박제되면
// 배포된 강의실에서 계정 메뉴가 엉뚱한 오리진으로 사람을 보낸다(로그인 화면이
// 이미 겪은 사고, app/login/page.tsx 참고). 이 앱은 애초에 정적 렌더링의
// 이득이 없으므로(ADR-0015는 공개 표면에만 SSR을 요구했다) 손해가 없다.
export const dynamic = "force-dynamic";

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
  title: "Laurio 클래스",
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
          <div className="mx-auto flex h-[72px] max-w-[1200px] items-center justify-between px-6">
            <Link
              href="/"
              data-testid="classroom-header-brand"
              className="text-[21px] font-bold tracking-[-0.01em] text-ink"
            >
              Laurio <span className="text-[15px] font-normal text-ink/45">클래스</span>
            </Link>
            <div className="flex items-center gap-2">
              <NotificationBell />
              <AccountMenu />
            </div>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
