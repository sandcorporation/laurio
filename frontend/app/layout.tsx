import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans_KR } from "next/font/google";
import type { ReactNode } from "react";
import "./globals.css";

// 「공모 게시판」 서체(FE-02, #27) — 시안(design/*.dc.html)이 확정한 두 서체다.
// next/font 로 셀프호스팅해 레이아웃 시프트 없이 로드하고, 실패해도 무너지지
// 않도록 폴백 스택은 app/tokens.css 의 --font-sans/--font-mono 가 최종 결정한다.
// 여기서는 변수만 채운다.
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

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko" className={`${ibmPlexSansKR.variable} ${ibmPlexMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
