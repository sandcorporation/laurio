"use client";

// 왼쪽 내비(#422, 부모 #421) — 시안 `docs/design/operator/Payouts.dc.html` 의
// 골간. 묶음·순서·라우트는 `lib/nav/nav-groups.ts` 가 선언한 데이터를 그대로
// 그린다 — 화면마다 흩어 놓지 않는다(spec #421 Implementation Decisions
// 「골간」).
//
// 지금 보는 화면은 `usePathname()` 으로 판정한다. 열둘 전부(#427 이 마지막
// 둘 — 홈·로그인 — 을 옮겼다) 골간을 쓰므로, 어느 화면에서든 다른 화면으로
// 바로 간다(user story 1) — 홈으로 되돌아가지 않는다.
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useSession } from "@/lib/auth/use-session";
import { NAV_GROUPS } from "@/lib/nav/nav-groups";
import { useNavQueueCounts } from "@/lib/nav/use-nav-queue-counts";

import { ThemeToggle } from "./theme-toggle";

import type { ThemePreference } from "@/lib/theme/preference";

function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function Sidebar({ themePreference }: { themePreference: ThemePreference }) {
  const pathname = usePathname();
  const session = useSession();
  const counts = useNavQueueCounts(session.status === "authenticated");

  return (
    <aside
      data-testid="operator-sidebar"
      className="flex w-[208px] shrink-0 flex-col border-r border-rule bg-paper"
    >
      {/* 브랜드는 이 좁은 칸(208px)을 혼자 쓴다 — 테마 토글을 옆에 두니 「Codemit
          운영자」가 두 줄로 깨졌다(2026-09-16 스크린샷). 토글은 아래 계정 줄 옆으로
          내렸다. */}
      <div className="flex h-[60px] items-center border-b border-rule px-4">
        <span className="text-base font-bold tracking-[-0.01em] whitespace-nowrap">
          Codemit<span className="ml-1.5 text-xs text-attention">운영자</span>
        </span>
      </div>

      <nav aria-label="운영자 내비게이션" className="flex flex-col gap-4 py-4">
        {NAV_GROUPS.map((group) => (
          <div key={group.title} className="flex flex-col gap-0.5">
            <div className="px-4 pb-1.5 text-[10.5px] tracking-[0.1em] text-ink/30">
              {group.title}
            </div>
            {group.items.map((item) => {
              const active = isActive(pathname, item.href);
              const count =
                item.countKey && counts.status === "loaded" ? counts.counts[item.countKey] : null;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  data-testid={item.testId}
                  aria-current={active ? "page" : undefined}
                  className={`flex items-center justify-between gap-2.5 border-l-2 py-1.5 pr-3.5 pl-3 text-[13px] ${
                    active
                      ? "border-attention bg-surface font-medium text-ink"
                      : "border-transparent font-normal text-ink/62 hover:text-ink"
                  }`}
                >
                  <span>{item.label}</span>
                  {count !== null && (
                    <span
                      data-testid={`${item.testId}-badge`}
                      className="font-mono text-xs text-ink/62"
                    >
                      {count}
                    </span>
                  )}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="mt-auto flex flex-col gap-2.5 border-t border-rule px-4 py-3.5 text-xs text-ink/62">
        {session.status === "authenticated" ? (
          <span data-testid="sidebar-account">
            {session.user.username} · {session.user.is_superuser ? "상위 등급" : "일반 등급"}
          </span>
        ) : (
          <span data-testid="sidebar-account">불러오는 중...</span>
        )}
        <ThemeToggle initialPreference={themePreference} />
      </div>
    </aside>
  );
}
