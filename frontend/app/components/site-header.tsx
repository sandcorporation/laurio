// 모든 페이지에 서는 헤더(#93, spec #92). 서버 컴포넌트다 — 헤더는 색인 대상인
// 공개 페이지(`/`, `/contests`, ...)에도 실리므로 ADR-0015 의 경계를 지킨다.
// 세션에 따라 갈리는 조각만 `HeaderSessionZone`(벨 + 세션 슬롯, #237)으로 떼어
// 클라이언트에 맡긴다.
//
// **역할로 갈리지 않는다.** CONTEXT.md 는 한 사람이 어떤 Contest 에서는
// Sponsor 이고 다른 Contest 에서는 Developer 일 수 있다고 정의한다 — 제출·개최
// 이력이 있든 없든 이 헤더는 항상 같은 네 조각(브랜드·공모전·개최 CTA·세션
// 슬롯)이다. 세부는 이미 `/console` 이 나눈다.
//
// 개최 CTA 는 로그인 여부와 무관하게 항상 보인다 — `/console/contests/new`
// 로 바로 링크한다. 로그인하지 않은 사람이 눌러도 미들웨어(middleware.ts)가
// `/login?next=...` 로 보낸다. "무엇이 필요한지 미리 보는 것"이 목적이므로 이
// 리다이렉트는 결함이 아니다.
import Link from "next/link";

import { HeaderSessionZone } from "./header-session-zone";

export function SiteHeader() {
  return (
    <header data-testid="site-header" className="border-b border-rule bg-surface">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-10">
        <Link href="/" data-testid="header-brand" className="text-lg font-semibold text-ink">
          Laurio
        </Link>

        <nav aria-label="주 메뉴" className="flex flex-wrap items-center gap-3 text-sm">
          <Link
            href="/contests"
            data-testid="header-nav-contests"
            className="text-ink/80 hover:text-ink"
          >
            공모전
          </Link>
          <Link
            href="/console/contests/new"
            data-testid="header-cta-new-contest"
            className="rounded-sm border border-ink px-3 py-1.5 font-medium text-ink hover:bg-ink hover:text-paper"
          >
            공모전 개최
          </Link>
          <HeaderSessionZone />
        </nav>
      </div>
    </header>
  );
}
