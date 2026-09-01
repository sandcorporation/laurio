import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

// 색인 대상이 아니다(ADR-0015·ADR-0021) — 그래서 공개 앱과 달리 OG 태그·서체
// 셀프호스팅 같은 공개 표면 전용 장치가 없다. 이 앱의 유일한 독자는 로그인한
// Operator다.
export const metadata: Metadata = {
  title: "Laurio Operator",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
