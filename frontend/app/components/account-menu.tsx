"use client";

// 헤더 계정 메뉴 — 공개 앱 (#375, parent spec #371). 예전에는 로그인한 사람에게
// 「내 콘솔」 링크 하나만 보였다(이 파일 이전의 `session-slot.tsx`) — 그 링크가
// 가리키던 콘솔 현관(`/console`)이 없어지면서, 그 화면에 있던 진입점(내 참가
// 현황·내 공모전·내 정보)과 로그아웃을 이 메뉴가 대신 연다.
//
// **메뉴 모양·바깥을 눌러 닫는 동작은 강의실의 계정 메뉴를 그대로 옮겼다**
// (`classroom/app/components/account-menu-client.tsx`, #306) — 두 앱이 같은
// 요소를 다르게 그리면 다시 갈라진다(#358가 이미 겪었다, #370의 브랜드 가드).
//
// `contestProductEnabled()`는 공개 설정(`lib/public-config.ts`)이라 클라이언트에서
// 직접 읽어도 된다(`lib/contest-switch.ts`) — 서버를 거칠 이유가 없다. `classroomUrl`은
// 그렇지 않은 서버 전용 값(`CODEMIT_CLASSROOM_ORIGIN`)이라 부모(`SiteHeader`,
// 서버 컴포넌트)가 계산해 내려준다(`lib/auth/classroom-link.ts`).
import Link from "next/link";
import { useState } from "react";

import { contestProductEnabled } from "@/lib/contest-switch";

export function AccountMenu({ classroomUrl }: { classroomUrl: string }) {
  const [open, setOpen] = useState(false);

  async function handleLogout() {
    setOpen(false);
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    window.location.href = "/login";
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        data-testid="account-menu-trigger"
        aria-expanded={open}
        className="border border-rule px-3 py-1.5 text-[13px] text-ink hover:border-ink"
      >
        내 계정
      </button>

      {open && (
        <>
          {/* 바깥을 눌러 닫는다 — 메뉴 자체보다 아래, 나머지 화면보다 위. */}
          <button
            type="button"
            aria-label="메뉴 닫기"
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-10 cursor-default"
          />
          <div
            data-testid="account-menu-panel"
            className="absolute right-0 z-20 mt-1.5 flex w-44 flex-col border border-rule bg-surface text-[13px]"
          >
            <Link
              href="/console/participation"
              data-testid="account-menu-participation-link"
              onClick={() => setOpen(false)}
              className="px-3 py-2 text-ink hover:bg-paper"
            >
              내 참가 현황
            </Link>
            {contestProductEnabled() && (
              <Link
                href="/console/contests"
                data-testid="account-menu-my-contests-link"
                onClick={() => setOpen(false)}
                className="px-3 py-2 text-ink hover:bg-paper"
              >
                내 공모전
              </Link>
            )}
            <Link
              href="/console/profile"
              data-testid="account-menu-profile-link"
              onClick={() => setOpen(false)}
              className="px-3 py-2 text-ink hover:bg-paper"
            >
              내 정보
            </Link>
            <a
              href={classroomUrl}
              data-testid="account-menu-classroom-link"
              className="px-3 py-2 text-ink hover:bg-paper"
            >
              클래스로 가기
            </a>
            <button
              type="button"
              onClick={handleLogout}
              data-testid="account-menu-logout"
              className="border-t border-rule px-3 py-2 text-left text-ink hover:bg-paper"
            >
              로그아웃
            </button>
          </div>
        </>
      )}
    </div>
  );
}
