import type { Metadata } from "next";
import { IBM_Plex_Mono } from "next/font/google";
import { cookies } from "next/headers";
import localFont from "next/font/local";
import type { ReactNode } from "react";

import "./globals.css";

import { publicConfigFromEnv, publicConfigScript } from "@/lib/public-config";
import { THEME_COOKIE, parseThemePreference, themeAttribute } from "@/lib/theme/preference";

import { AppShell } from "./components/app-shell";

// 색인 대상이 아니다(ADR-0015·ADR-0021) — 그래서 공개 앱과 달리 OG 태그 같은
// 공개 표면 전용 장치가 없다. 이 앱의 유일한 독자는 로그인한 Operator다.
export const metadata: Metadata = {
  title: "Codemit Operator",
  robots: { index: false, follow: false },
};

// 서체는 공개 앱·강의실과 같다(#422, #298) — 세 앱을 오가는 사람이 글꼴이
// 갈리는 것을 먼저 알아챈다. 파일도 `app/fonts/`에 같은 것을 담는다(공유
// 패키지로 빼지 않은 이유와 갈라지지 않게 지키는 방법은
// `lib/design/tokens.test.ts`).
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

// **정적으로 구워지면 안 된다**(#297의 원칙 — `lib/rendering/runtime-config.test.ts`
// 와 같은 이유가 강의실에 있다). 여기서는 `cookies()`를 읽으므로 Next가 이미
// 이 레이아웃을 동적으로 렌더한다 — 명시해 두어 다음 사람이 서버 전용 값을
// 더할 때 조용히 정적으로 굳는 것을 막는다.
export const dynamic = "force-dynamic";

// **테마 표시를 여기서 붙인다**(#422, #397/#398과 같은 이유). 요청마다 쿠키를
// 읽어 문서 루트(`<html>`)에 `data-theme`를 붙인 채 그리므로, 다크를 고른
// 사람에게는 첫 화면부터 다크 HTML이 나가 라이트가 잠깐도 비치지 않는다.
export default async function RootLayout({ children }: { children: ReactNode }) {
  const cookieStore = await cookies();
  const themePreference = parseThemePreference(cookieStore.get(THEME_COOKIE)?.value);

  return (
    <html
      lang="ko"
      data-theme={themeAttribute(themePreference)}
      className={`${pretendard.variable} ${ibmPlexMono.variable}`}
    >
      <head>
        {/* 공개 설정을 브라우저에 한 번 넘긴다(#711, lib/public-config.ts) — Sentry
            초기화보다 먼저 읽히도록 <head> 에 둔다. */}
        <script
          id="codemit-public-config"
          dangerouslySetInnerHTML={{ __html: publicConfigScript(publicConfigFromEnv(process.env)) }}
        />
      </head>
      <body>
        <AppShell themePreference={themePreference}>{children}</AppShell>
      </body>
    </html>
  );
}
