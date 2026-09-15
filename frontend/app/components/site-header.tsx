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
//
// **공모전 제품 스위치(#271)가 꺼지면 이 둘을 뺀다.** 앱은 진입점을 감출 뿐이고
// (백엔드가 유일한 집행자다), 이 헤더가 정확히 그 진입점 둘을 쥐고 있다 —
// "공모전" 링크와 "공모전 개최" CTA.
//
// **개최 CTA 는 유료 스위치도 함께 본다**(#413). 무료 개최(#415)가 생기기 전까지
// `/console/contests/new`는 본인확인·견적·결제로 이어지는 유료 개최 흐름
// 하나뿐이라, 유료 스위치가 꺼지면 이 CTA 도 함께 뺀다 — 안 그러면 누르는
// 순간 견적·개최 API 가 404 를 내는 막다른 링크가 된다. "공모전" 목록 링크는
// 유료와 무관하므로 공모전 스위치만 본다.
import Link from "next/link";

import { buttonClass } from "@/lib/ui/classnames";
import { contestProductEnabled, paidContestProductEnabled } from "@/lib/contest-switch";
import { classroomAppOrigin } from "@/lib/auth/classroom-link";
import type { ThemePreference } from "@/lib/theme/preference";

import { HeaderSessionZone } from "./header-session-zone";
import { LogoMark } from "./logo-mark";
import { ThemeToggle } from "./theme-toggle";

export function SiteHeader({ themePreference }: { themePreference: ThemePreference }) {
  // 계정 메뉴의 「클래스로 가기」가 가리킬 곳(#375, spec #371) — 서버 전용
  // 환경변수라 여기(서버 컴포넌트)에서 읽어 클라이언트 자식에게 내려준다
  // (lib/auth/classroom-link.ts). 이 값이 빌드 시점에 구워지지 않는 것은
  // `app/layout.tsx`의 `force-dynamic`이 보장한다(#297).
  const classroomUrl = classroomAppOrigin();

  return (
    <header data-testid="site-header" className="border-b border-rule bg-surface">
      <div className="mx-auto flex h-[72px] max-w-[1200px] flex-wrap items-center justify-between gap-3 px-6">
        <Link
          href="/"
          data-testid="header-brand"
          className="flex items-center gap-2 text-[21px] font-bold tracking-[-0.01em] text-ink"
        >
          <LogoMark className="h-6 w-6" />
          Codemit
        </Link>

        <nav aria-label="주 메뉴" className="flex flex-wrap items-center gap-3 text-sm">
          {contestProductEnabled() && (
            <>
              <Link
                href="/contests"
                data-testid="header-nav-contests"
                className="text-ink/80 hover:text-ink"
              >
                공모전
              </Link>
              {paidContestProductEnabled() && (
                <Link
                  href="/console/contests/new"
                  data-testid="header-cta-new-contest"
                  className={buttonClass("primary", "sm")}
                >
                  공모전 개최
                </Link>
              )}
            </>
          )}
          <ThemeToggle initialPreference={themePreference} />
          <HeaderSessionZone classroomUrl={classroomUrl} />
        </nav>
      </div>
    </header>
  );
}
