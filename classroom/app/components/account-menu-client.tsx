"use client";

// 헤더의 계정 메뉴 (#306) — 클래스 앱에는 자기 계정을 볼 곳이 전혀 없었다. 지금
// 누구로 들어와 있는지를 보여주고, 프로필·알림·탈퇴·로그아웃으로 가는 문을 연다.
//
// **프로필·탈퇴는 공개 앱으로 나간다** — 회원을 공유하는 두 앱에 같은 개인정보
// 화면을 두 번 만들지 않는다(docs/features/classroom.md). 알림만 이 앱 안에
// 있다(#304, `NotificationBell`이 이미 그 자리를 가리킨다) — 클래스 알림만
// 걸러 보여주기 때문이다. 그 두 외부 링크에는 이 앱의 오리진을 `from_origin`으로
// 실어 보낸다(`lib/auth/return-link.ts`) — 공개 앱이 「돌아가기」를 보여줄 수
// 있게(#307), 유효성 검증은 받는 쪽(공개 앱의 resolveSiblingOrigin) 몫이다.
//
// **로그인 여부는 `useMe`로 판정한다** — 이 앱에 `HeaderSessionZone`(공개 앱)
// 같은 전용 세션 조회 장치가 없어, 이미 있는 `/accounts/me` 호출을 그대로 신호로
// 쓴다(알림 종과 같은 이유, `use-unread-count.ts`). 로딩 중에는 아무것도 단언하지
// 않고(로그인 여부가 아직 갈리지 않았다), 실패(401 등)면 로그인 링크로 대체한다.
import Link from "next/link";
import { useState } from "react";

import { accountLabel, useMe } from "@/lib/auth/use-me";

import { buttonClass } from "./ui";

export function AccountMenuClient({
  profileUrl,
  withdrawUrl,
}: {
  profileUrl: string;
  withdrawUrl: string;
}) {
  const me = useMe();
  const [open, setOpen] = useState(false);

  if (me.status === "loading") {
    return <span data-testid="account-menu-loading" aria-hidden="true" />;
  }

  if (me.status === "error") {
    return (
      <Link
        href="/login"
        data-testid="account-menu-login-link"
        className={buttonClass("secondary", "sm")}
      >
        로그인
      </Link>
    );
  }

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
        {accountLabel(me)}
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
            <a
              href={profileUrl}
              data-testid="account-menu-profile-link"
              className="px-3 py-2 text-ink hover:bg-paper"
            >
              프로필
            </a>
            <Link
              href="/notifications"
              data-testid="account-menu-notifications-link"
              onClick={() => setOpen(false)}
              className="px-3 py-2 text-ink hover:bg-paper"
            >
              알림
            </Link>
            {/* 되돌릴 수 없는 행위는 색으로 먼저 구별된다(#344) — 탈퇴는 주의색,
                로그아웃은 보통이다(되돌릴 수 있다: 다시 로그인하면 그만이다).
                이 메뉴는 이 앱에서 한 번만 그리므로 화면마다 반복될 위험이
                없어 buttonClass를 거치지 않고 여기서 직접 정한다. */}
            <a
              href={withdrawUrl}
              data-testid="account-menu-withdraw-link"
              className="border-t border-rule px-3 py-2 text-attention hover:bg-paper"
            >
              탈퇴
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
