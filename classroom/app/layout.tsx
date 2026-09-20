import type { Metadata } from "next";
import { IBM_Plex_Mono } from "next/font/google";
import { cookies } from "next/headers";
import Link from "next/link";
import localFont from "next/font/local";
import type { ReactNode } from "react";

import { MeProvider } from "@/lib/auth/me-context";
import { EventStreamProvider } from "@/lib/events/stream-context";
import { classroomAppOrigin } from "@/lib/seo/origin";
import { THEME_COOKIE, parseThemePreference, themeAttribute } from "@/lib/theme/preference";

import { AccountMenu } from "./components/account-menu";
import { NotificationBell } from "./components/notification-bell";
import { LogoMark } from "./components/logo-mark";
import { SiteFooter } from "./components/site-footer";
import { ThemeToggle } from "./components/theme-toggle";

import "./globals.css";

// **정적으로 구워지면 안 된다** (#297, lib/rendering/runtime-config.test.ts).
// `AccountMenu`가 이 레이아웃 트리에서 `headers()`와 `CODEMIT_WEB_ORIGIN`·
// `CODEMIT_CLASSROOM_ORIGIN`을 읽는다 — 그 값이 빌드 머신 것으로 박제되면
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

// **기본은 색인 대상이 아니다**(ADR-0015·ADR-0021/0037과 같은 원칙 — 운영자
// 앱 operator/app/layout.tsx 참고). 이 앱의 독자는 대부분 로그인한 참여자·
// 강사다. **유일한 예외는 랜딩이다**(#395, `app/page.tsx`) — 비로그인
// 요청으로 루트를 열면 그 파일의 `generateMetadata`가 `robots: { index: true
// }`로 이 기본값을 덮는다.
//
// `metadataBase`는 강의실 자신의 오리진이다(#395) — 랜딩의 OG 이미지·
// canonical 같은 상대 경로가 이 값을 기준으로 절대 URL 이 된다.
export const metadata: Metadata = {
  metadataBase: new URL(classroomAppOrigin()),
  title: "Codemit 클래스",
  robots: { index: false, follow: false },
};

// "/" 로 가는 링크가 최소 하나 있어야 고아 라우트 검사(lib/routes/orphan-routes.test.ts,
// #166)가 홈을 고아로 잡지 않는다 — 공개 앱의 SiteHeader(app/components/site-header.tsx)와
// 같은 자리다.
//
// **`MeProvider`가 `body` 전체를 감싼다**(#322) — 헤더의 종·계정 메뉴뿐 아니라
// `useMe()`를 부르는 페이지(예: 제출 화면)도 같은 세션 조회 하나를 나눠 쓴다.
// `MeProvider`는 클라이언트 컴포넌트지만 그 `children`으로 서버 컴포넌트인
// `AccountMenu`·`{children}`을 그대로 받을 수 있다 — Next가 문서로 보장하는
// "서버 컴포넌트를 클라이언트 컴포넌트의 children으로 넘기기" 패턴이라 그
// 아래 트리가 클라이언트 컴포넌트로 바뀌지는 않는다.
//
// **`EventStreamProvider`가 그 안에서 탭마다 스트림 하나를 연다**(#379,
// ADR-0046) — `MeProvider` 안에 둔 이유는 세션이 확인되기 전에는 스트림을
// 열지 않기 위해서다(`lib/events/stream-context.tsx`). 헤더든 `{children}`이든
// 이 트리 아래 어디서나 `useEventStream()`으로 같은 연결을 나눠 구독한다.
//
// **테마 표시를 여기서 붙인다**(#398, spec #396) — 공개 앱의 `app/layout.tsx`와
// 같은 이유·같은 모양이다. 요청마다 쿠키를 읽어 문서 루트에 `data-theme`를
// 붙인 채 그리므로 다크를 고른 사람에게 라이트가 잠깐도 비치지 않는다. 이
// 레이아웃은 이미 `force-dynamic`이라 쿠키 값이 빌드 시점에 박히지 않는다.
export default async function RootLayout({ children }: { children: ReactNode }) {
  const cookieStore = await cookies();
  const themePreference = parseThemePreference(cookieStore.get(THEME_COOKIE)?.value);

  return (
    <html
      lang="ko"
      data-theme={themeAttribute(themePreference)}
      className={`${pretendard.variable} ${ibmPlexMono.variable}`}
    >
      <body>
        <MeProvider>
          <EventStreamProvider>
            <header className="border-b border-rule bg-surface">
              <div className="mx-auto flex h-[72px] max-w-[1200px] items-center justify-between px-6">
                <Link
                  href="/"
                  data-testid="classroom-header-brand"
                  className="flex items-center gap-2 text-[21px] font-bold tracking-[-0.01em] text-ink"
                >
                  <LogoMark className="h-6 w-6" />
                  Codemit <span className="text-[15px] font-normal text-ink/45">클래스</span>
                </Link>
                <div className="flex items-center gap-2">
                  <ThemeToggle initialPreference={themePreference} />
                  <NotificationBell />
                  <AccountMenu />
                </div>
              </div>
            </header>
            {children}
            <SiteFooter />
          </EventStreamProvider>
        </MeProvider>
      </body>
    </html>
  );
}
