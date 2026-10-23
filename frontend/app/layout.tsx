import type { Metadata } from "next";
import { cookies } from "next/headers";
import localFont from "next/font/local";
import type { ReactNode } from "react";
import "./globals.css";

import { metricsSnippetSrc, publicConfigFromEnv, publicConfigScript } from "@/lib/public-config";
import { webAppOrigin } from "@/lib/seo/origin";
import { THEME_COOKIE, parseThemePreference, themeAttribute } from "@/lib/theme/preference";

import { SiteFooter } from "./components/site-footer";
import { SiteHeader } from "./components/site-header";

// 본문 서체는 Pretendard, 등폭은 IBM Plex Mono 다.
//
// 두 서체 다 `next/font/local` 로 저장소에 담은 파일에서 로드한다(`app/fonts/`).
// Pretendard 는 Google Fonts 에 없고, IBM Plex Mono 는 Google 서체 로더가
// 빌드 때마다 fonts.gstatic.com 을 불러 이미지 굽기가 외부 네트워크에 매달렸다
// (#743) — 그래서 latin 서브셋의 굵기 셋(400·500·600)을 받아 담았다. 그래도 `next/font` 를 쓰는
// 이유는 이 앱이 원래 갖고 있던 성질을 잃지 않기 위해서다: 셀프호스팅(외부
// 호스트의 가동에 기대지 않는다)과 폴백 메트릭 보정(스왑 순간의 레이아웃
// 시프트를 줄인다).
//
// 파일은 **가변폰트 전체**(1.96MB)다. 상용 음절만 담은 서브셋(무게당 0.26MB)이
// 훨씬 가볍지만, 이 앱은 사용자가 지은 이름과 공모전 제목을 그대로 렌더하므로
// 그 안의 드문 음절이 문장 중간에 시스템 폰트로 떨어져 서체가 섞인다 — 무게를
// 아끼는 대신 그 섞임을 감수하지 않기로 한다.
//
// 시안(design/*.dc.html)이 고른 것은 IBM Plex Sans KR 이었지만 그것은 브랜드가
// 정해지기 전의 자리표시자였다(app/tokens.css 의 첫 주석). 폰트를 정한 ADR 은
// 없으므로 이 교체는 어떤 결정도 뒤집지 않는다. 등폭은 시안 그대로 둔다.
//
// 폴백 스택의 최종 결정은 여전히 app/tokens.css 의 --font-sans/--font-mono 다.
// 여기서는 변수만 채운다.
const pretendard = localFont({
  src: "./fonts/PretendardVariable.woff2",
  // 가변폰트 wght 축의 전 범위. 이 값을 좁히면 브라우저가 범위 밖 굵기를
  // 합성(faux bold)해 버려 가변폰트를 쓰는 뜻이 없어진다.
  weight: "45 920",
  variable: "--font-pretendard",
  display: "swap",
});

const ibmPlexMono = localFont({
  src: [
    { path: "./fonts/IBMPlexMono-Regular.woff2", weight: "400", style: "normal" },
    { path: "./fonts/IBMPlexMono-Medium.woff2", weight: "500", style: "normal" },
    { path: "./fonts/IBMPlexMono-SemiBold.woff2", weight: "600", style: "normal" },
  ],
  variable: "--font-ibm-plex-mono",
  display: "swap",
});

// **기준 주소(metadataBase)와 기본 OG·트위터 카드**(#394, #391 Implementation
// Decisions 「공개 앱 메타데이터·SEO」). 설명은 공모전만 말한다 — 이 앱은
// 공모전 이야기만 한다(`app/page.tsx` 「빈 화면이 합의된 답이다」와 같은 원칙).
// 기본 OG 이미지는 `app/opengraph-image.tsx`(Next 파일 컨벤션)가 로고와 함께
// 그린다 — 공모전 상세·개발자 프로필은 각자의 `opengraph-image.tsx`로 이 기본을
// 덮는다.
//
// **제목 템플릿**(`%s · Codemit`)은 자식 페이지가 문자열 하나만 주는 제목에
// 적용된다 — 홈처럼 제목을 아예 안 주는 페이지는 `default`("Codemit")를 그대로
// 쓴다.
export const metadata: Metadata = {
  metadataBase: new URL(webAppOrigin()),
  title: { default: "Codemit", template: "%s · Codemit" },
  description: "발주자가 상금을 걸고 요구사항을 공개하면, 개발자들이 만들어 제출하는 공개 공모전 플랫폼",
  openGraph: {
    title: "Codemit",
    description: "발주자가 상금을 걸고 요구사항을 공개하면, 개발자들이 만들어 제출하는 공개 공모전 플랫폼",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Codemit",
    description: "발주자가 상금을 걸고 요구사항을 공개하면, 개발자들이 만들어 제출하는 공개 공모전 플랫폼",
  },
};

// **정적으로 구워지면 안 된다**(#297, #375, `lib/rendering/runtime-config.test.ts`).
// 헤더의 `SiteHeader`가 이 레이아웃 트리에서 `CODEMIT_CLASSROOM_ORIGIN`
// (`lib/auth/classroom-link.ts`, 계정 메뉴의 「클래스로 가기」)을 읽는다 — 그
// 값이 빌드 머신 것(=비어 있음)으로 박제되면 배포된 공개 앱의 헤더가 dev
// 폴백(`http://127.0.0.1:53002`)으로 사람을 보낸다(강의실 로그인 화면이 이미
// 겪은 사고, classroom/app/login/page.tsx 참고). 공개 다섯 화면은 이미 각자
// 백엔드를 요청 시점에 호출하므로(`page.tsx`의 `fetchHomeCuration` 등) 이
// 레이아웃을 통째로 동적으로 돌려도 잃는 것이 없다.
export const dynamic = "force-dynamic";

// 헤더는 모든 페이지에 서므로 여기서 딱 한 번 조립한다(#93, spec #92). 세션
// 슬롯을 뺀 나머지는 서버 컴포넌트라 인증 구역(app/console/**)을 포함해 어느
// 페이지가 이 레이아웃 아래 걸리든 렌더링 방식이 갈리지 않는다.
//
// **테마 표시를 여기서 붙인다**(#398, spec #396). 요청마다 쿠키를 읽어 문서
// 루트(`<html>`)에 `data-theme`를 붙인 채 그리므로, 다크를 고른 사람에게는
// 첫 화면부터 다크 HTML 이 나가 라이트가 잠깐도 비치지 않는다(#397 의
// `light-dark()`/`color-scheme` 규칙이 이 속성을 본다). 이 레이아웃은 이미
// `force-dynamic`이라 쿠키 값이 빌드 시점에 박히지 않는다.
export default async function RootLayout({ children }: { children: ReactNode }) {
  const cookieStore = await cookies();
  const themePreference = parseThemePreference(cookieStore.get(THEME_COOKIE)?.value);
  const metricsSrc = metricsSnippetSrc(process.env);

  return (
    <html
      lang="ko"
      data-theme={themeAttribute(themePreference)}
      className={`${pretendard.variable} ${ibmPlexMono.variable}`}
    >
      <head>
        {/* 공개 설정을 브라우저에 한 번 넘긴다(#711, lib/public-config.ts) — 화면
            코드와 Sentry 초기화보다 먼저 읽히도록 <head> 에 둔다. */}
        <script
          id="codemit-public-config"
          dangerouslySetInnerHTML={{ __html: publicConfigScript(publicConfigFromEnv(process.env)) }}
        />
        {/* 방문 메트릭 스니펫(Sandcorp 공통, #785) — 실행 env 에 주소가 있을 때만 그린다. 쿠키 없이
            경로 변경마다 조회 한 건을 보내고, 운영자 앱에는 넣지 않는다. */}
        {metricsSrc && <script defer src={metricsSrc} data-site="codemit" />}
      </head>
      <body>
        <SiteHeader themePreference={themePreference} />
        {children}
        <SiteFooter />
      </body>
    </html>
  );
}
