import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans_KR } from "next/font/google";
import type { ReactNode } from "react";
import "./globals.css";

import { SiteHeader } from "./components/site-header";

// 「공모 게시판」 서체(FE-02, #27) — 시안(design/*.dc.html)이 확정한 두 서체다.
// next/font 로 셀프호스팅해 레이아웃 시프트 없이 로드하고, 실패해도 무너지지
// 않도록 폴백 스택은 app/tokens.css 의 --font-sans/--font-mono 가 최종 결정한다.
// 여기서는 변수만 채운다.
//
// subsets 는 "latin" 만 준다 — "korean" 은 next/font 15.5.24 기준 이 폰트에
// 존재하지 않는 값이라 build/dev 가 즉시 `Unknown subset 'korean' for font
// 'IBM Plex Sans KR'. Available subsets: 'latin', 'latin-ext'` 로 죽는다(직접
// 재현해 확인했다). 그리고 굳이 필요하지도 않다 — next/font/google 이 이
// subsets 로 하는 일은 <link rel=preload> 대상을 고르는 것뿐이고(글리프
// 포함 여부와는 무관하다), Google Fonts 가 내려주는 CSS 자체가 이미 이
// 패밀리의 한글 유니코드 레인지를 전부 포함한다 — 브라우저에서
// `document.fonts.check('16px "IBM Plex Sans KR"', '공개 공모전')` 이 실제로
// true 를 반환하고, 로드된 @font-face 목록에 한글 syllable 레인지(예:
// U+AC00-D7A3 대역)를 커버하는 항목이 잡히는 것으로 직접 확인했다. 즉 한글은
// 이미 IBM Plex Sans KR 로 렌더된다 — "korean" subset 을 추가하면 증상이
// 고쳐지는 게 아니라 빌드가 깨진다.
const ibmPlexSansKR = IBM_Plex_Sans_KR({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-ibm-plex-sans-kr",
  display: "swap",
});

const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-ibm-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Laurio",
  description: "발주자가 상금을 걸고 요구사항을 공개하면, 개발자들이 만들어 제출하는 공개 공모전 플랫폼",
};

// 헤더는 모든 페이지에 서므로 여기서 딱 한 번 조립한다(#93, spec #92). 세션
// 슬롯을 뺀 나머지는 서버 컴포넌트라 인증 구역(app/console/**)을 포함해 어느
// 페이지가 이 레이아웃 아래 걸리든 렌더링 방식이 갈리지 않는다.
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko" className={`${ibmPlexSansKR.variable} ${ibmPlexMono.variable}`}>
      <body>
        <SiteHeader />
        {children}
      </body>
    </html>
  );
}
