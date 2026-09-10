import Link from "next/link";
import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

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
    <html lang="ko">
      <body>
        <header>
          <Link href="/" data-testid="classroom-header-brand">
            Laurio 강의실
          </Link>
        </header>
        {children}
      </body>
    </html>
  );
}
