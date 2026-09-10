import type { Metadata } from "next";
import { IBM_Plex_Mono } from "next/font/google";
import localFont from "next/font/local";
import type { ReactNode } from "react";
import "./globals.css";

import { SiteHeader } from "./components/site-header";

// 본문 서체는 Pretendard, 등폭은 IBM Plex Mono 다.
//
// **Pretendard 는 Google Fonts 에 없다** — 그래서 본문만 `next/font/local` 로
// 저장소에 담은 파일에서 로드한다(`app/fonts/`). 그래도 `next/font` 를 쓰는
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
    <html lang="ko" className={`${pretendard.variable} ${ibmPlexMono.variable}`}>
      <body>
        <SiteHeader />
        {children}
      </body>
    </html>
  );
}
