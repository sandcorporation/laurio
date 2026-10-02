"use client";

// 왼쪽 내비(#422, 부모 #421) — 시안 `docs/design/operator/Payouts.dc.html` 의
// 골간. 묶음·순서·라우트는 `lib/nav/nav-groups.ts` 가 선언한 데이터를 그대로
// 그린다 — 화면마다 흩어 놓지 않는다(spec #421 Implementation Decisions
// 「골간」).
//
// 지금 보는 화면은 `usePathname()` 으로 판정한다. 열둘 전부(#427 이 마지막
// 둘 — 홈·로그인 — 을 옮겼다) 골간을 쓰므로, 어느 화면에서든 다른 화면으로
// 바로 간다(user story 1) — 홈으로 되돌아가지 않는다.
//
// **좁은 화면에서는 접힌다**(#523). 208px 칸이 늘 펼쳐져 있으면 390px 휴대폰에서
// 본문이 150px 남짓만 남았다. `md`(768px) 미만에서는 칸을 숨기고 머리 줄
// (`MobileBar`)의 메뉴 버튼으로 같은 내용을 덮개(`Drawer`)로 연다. 넓은 화면은
// 예전 그대로다 — 같은 `SidebarBody` 를 두 자리가 나눠 그린다.
//
// 덮개는 **열려 있을 때만 그리고**, 그동안 넓은 화면용 칸은 내용을 비운다. 둘 다
// 그리면 내비 링크의 data-testid 가 문서에 두 벌 생겨 e2e 의 단일 요소 조회가 깨진다.
// 넓은 화면에서는 덮개가 열릴 일이 없다(버튼이 `md:hidden` 이고, 넓어지면 닫는다).
//
// 열고 닫기의 약속(#523 AC):
// - 버튼이 `aria-expanded`·`aria-controls` 로 상태와 대상을 말한다.
// - 열면 포커스가 덮개 안(지금 화면 항목, 없으면 첫 항목)으로 가고, 닫으면 버튼으로
//   돌아온다. 덮개 밖(머리 줄·본문)은 `inert` 라 Tab 이 덮개 뒤로 사라지지 않는다 —
//   그렇다고 덮개에 가두지도 않는다(Tab 은 브라우저 주소창으로 나갔다 돌아온다).
// - Esc · 바깥(어두운 막) 누르기 · 닫기 버튼 · 항목 고르기(주소가 바뀜)로 닫힌다.
// - 미끄러져 들어오는 움직임은 `motion-safe:` 라 움직임 줄이기 설정이면 없다.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, type RefObject } from "react";

import { useSession, type OperatorSessionState } from "@/lib/auth/use-session";
import { NAV_GROUPS, isActiveHref, totalQueueCount } from "@/lib/nav/nav-groups";
import { useNavQueueCounts, type NavQueueCountsState } from "@/lib/nav/use-nav-queue-counts";

import { ThemeToggle } from "./theme-toggle";

import type { ThemePreference } from "@/lib/theme/preference";

const DRAWER_ID = "operator-nav-drawer";
const WIDE_QUERY = "(min-width: 768px)";

function Brand() {
  return (
    <span className="text-base font-bold tracking-[-0.01em] whitespace-nowrap">
      Codemit<span className="ml-1.5 text-xs text-attention">운영자</span>
    </span>
  );
}

function SidebarBody({
  pathname,
  session,
  counts,
  themePreference,
  navRef,
}: {
  pathname: string;
  session: OperatorSessionState;
  counts: NavQueueCountsState;
  themePreference: ThemePreference;
  navRef?: RefObject<HTMLElement | null>;
}) {
  return (
    <>
      <nav ref={navRef} aria-label="운영자 내비게이션" className="flex flex-col gap-4 py-4">
        {NAV_GROUPS.map((group) => (
          <div key={group.title} className="flex flex-col gap-0.5">
            <div className="px-4 pb-1.5 text-[10.5px] tracking-[0.1em] text-ink/30">
              {group.title}
            </div>
            {group.items.map((item) => {
              const active = isActiveHref(pathname, item.href);
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
    </>
  );
}

function MenuIcon() {
  return (
    <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none">
      <path d="M2 4h12M2 8h12M2 12h12" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

export function Sidebar({
  themePreference,
  menuOpen,
  onMenuOpenChange,
}: {
  themePreference: ThemePreference;
  menuOpen: boolean;
  onMenuOpenChange: (open: boolean) => void;
}) {
  const pathname = usePathname();
  const session = useSession();
  const counts = useNavQueueCounts(session.status === "authenticated");
  const total = counts.status === "loaded" ? totalQueueCount(counts.counts) : null;

  const buttonRef = useRef<HTMLButtonElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const wasOpen = useRef(false);

  // 항목을 골라 주소가 바뀌면 닫는다. 같은 항목을 다시 누른 경우는 주소가 그대로라
  // 아래 링크의 onClick 이 닫는다.
  useEffect(() => {
    onMenuOpenChange(false);
  }, [pathname, onMenuOpenChange]);

  // 열린 동안: Esc 로 닫고, 뒤 문서가 굴러가지 않게 하고, 화면이 넓어지면 닫는다
  // (넓은 화면에는 덮개가 없으므로 열린 채 남으면 본문이 inert 로 묶인다).
  useEffect(() => {
    if (!menuOpen) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onMenuOpenChange(false);
    }
    const wide = window.matchMedia(WIDE_QUERY);
    function onWide(event: MediaQueryListEvent) {
      if (event.matches) onMenuOpenChange(false);
    }
    document.addEventListener("keydown", onKey);
    wide.addEventListener("change", onWide);
    const root = document.documentElement;
    const previousOverflow = root.style.overflow;
    root.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      wide.removeEventListener("change", onWide);
      root.style.overflow = previousOverflow;
    };
  }, [menuOpen, onMenuOpenChange]);

  // 포커스 옮기기 — 열리면 덮개 안으로, 닫히면 버튼으로.
  useEffect(() => {
    if (menuOpen) {
      const nav = navRef.current;
      const target =
        nav?.querySelector<HTMLElement>('a[aria-current="page"]') ?? nav?.querySelector<HTMLElement>("a");
      target?.focus();
    } else if (wasOpen.current) {
      buttonRef.current?.focus();
    }
    wasOpen.current = menuOpen;
  }, [menuOpen]);

  return (
    <>
      <aside
        data-testid="operator-sidebar"
        className="hidden w-[208px] shrink-0 flex-col border-r border-rule bg-paper md:flex"
      >
        {/* 브랜드는 이 좁은 칸(208px)을 혼자 쓴다 — 테마 토글을 옆에 두니 「Codemit
            운영자」가 두 줄로 깨졌다(2026-09-16 스크린샷). 토글은 아래 계정 줄 옆으로
            내렸다. */}
        <div className="flex h-[60px] items-center border-b border-rule px-4">
          <Brand />
        </div>
        {/* 덮개가 열린 동안(좁은 화면이라 이 칸은 어차피 숨어 있다)은 내용을 비운다 —
            같은 내비가 두 벌 있으면 data-testid 가 겹친다. */}
        {!menuOpen && (
          <SidebarBody
            pathname={pathname}
            session={session}
            counts={counts}
            themePreference={themePreference}
          />
        )}
      </aside>

      <header
        data-testid="operator-mobile-bar"
        inert={menuOpen}
        className="sticky top-0 z-30 flex h-[52px] items-center gap-3 border-b border-rule bg-paper px-4 md:hidden"
      >
        <button
          ref={buttonRef}
          type="button"
          data-testid="operator-menu-button"
          aria-expanded={menuOpen}
          aria-controls={DRAWER_ID}
          onClick={() => onMenuOpenChange(true)}
          className="flex items-center gap-2 border border-rule bg-surface px-2.5 py-1.5 text-[12.5px] text-ink hover:border-ink"
        >
          <MenuIcon />
          <span>메뉴</span>
          {total !== null && total > 0 && (
            <span data-testid="operator-menu-queue-total" className="font-mono text-xs text-attention">
              <span className="sr-only">밀린 일 </span>
              {total}
              <span className="sr-only">건</span>
            </span>
          )}
        </button>
        <Brand />
      </header>

      {menuOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <button
            type="button"
            tabIndex={-1}
            aria-hidden="true"
            data-testid="operator-menu-backdrop"
            onClick={() => onMenuOpenChange(false)}
            className="absolute inset-0 h-full w-full cursor-default bg-ink/40"
          />
          <div
            id={DRAWER_ID}
            role="dialog"
            aria-modal="true"
            data-testid="operator-menu-drawer"
            aria-label="운영자 메뉴"
            className="relative flex h-full w-[264px] max-w-[85vw] flex-col overflow-y-auto border-r border-rule bg-paper motion-safe:animate-[op-drawer-in_160ms_ease-out]"
            onClick={(event) => {
              // 이미 보고 있는 항목을 다시 골라도 닫는다 — 주소가 그대로라 위 효과가 돌지 않는다.
              if ((event.target as HTMLElement).closest("a")) onMenuOpenChange(false);
            }}
          >
            <div className="flex h-[52px] shrink-0 items-center justify-between gap-3 border-b border-rule px-4">
              <Brand />
              <button
                type="button"
                data-testid="operator-menu-close"
                onClick={() => onMenuOpenChange(false)}
                className="border border-rule bg-surface px-2.5 py-1 text-[12px] text-ink/62 hover:border-ink hover:text-ink"
              >
                닫기
              </button>
            </div>
            <SidebarBody
              pathname={pathname}
              session={session}
              counts={counts}
              themePreference={themePreference}
              navRef={navRef}
            />
          </div>
        </div>
      )}
    </>
  );
}
