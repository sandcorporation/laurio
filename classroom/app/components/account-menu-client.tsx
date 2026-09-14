"use client";

// 헤더의 계정 메뉴 (#306, #376) — 클래스 앱에는 자기 계정을 볼 곳이 전혀 없었다.
// 지금 프로필·공모전으로 가기·로그아웃으로 가는 문을 연다.
//
// **공개 앱과 같은 모양이다**(#376, spec #371) — 두 앱의 계정 버튼이 다르게
// 동작하고 이름도 달랐던 것(공모전 앱 「내 콘솔」 / 강의실은 username)이 #371의
// 불만 중 하나였다. 버튼은 항상 「내 계정」이고(username을 화면에 그대로 그리면
// 안 된다는 규칙은 그대로다 — 아래), 메뉴 모양·바깥을 눌러 닫는 동작은
// `frontend/app/components/account-menu.tsx`를 그대로 옮겼다.
//
// **알림은 메뉴에 없다** — 바로 옆에 벨이 있어 같은 곳으로 가는 길이 헤더에
// 두 개였다(#371). 알림 화면(`/notifications`) 자체는 그대로 있고 벨이
// 가리킨다.
//
// **프로필은 공개 앱으로 나간다** — 회원을 공유하는 두 앱에 같은 개인정보
// 화면을 두 번 만들지 않는다(docs/features/classroom.md). 「공모전으로 가기」도
// 같은 공개 앱 오리진으로 나간다(#376) — 이 앱에서 공모전 앱으로 건너가는
// 유일한 문이다. 그 외부 링크들에는 이 앱의 오리진을 `from_origin`으로 실어
// 보낸다(`lib/auth/return-link.ts`) — 공개 앱이 「돌아가기」를 보여줄 수
// 있게(#307), 유효성 검증은 받는 쪽(공개 앱의 resolveSiblingOrigin) 몫이다.
// 「공모전으로 가기」는 프로필로 돌아가는 왕복이 아니라 그냥 건너가는
// 것이라 `from_origin`을 싣지 않는다 — 공개 앱 헤더의 「클래스로 가기」와
// 대칭이다(그것도 왕복 표시가 없다).
//
// **로그인 여부는 `useMe`로 판정한다** — 이 앱에 `HeaderSessionZone`(공개 앱)
// 같은 전용 세션 조회 장치가 없어, 이미 있는 `/accounts/me` 호출을 그대로 신호로
// 쓴다(알림 종과 같은 이유, `use-unread-count.ts`). 로딩 중에는 아무것도 단언하지
// 않고(로그인 여부가 아직 갈리지 않았다), 실패(401 등)면 로그인 링크로 대체한다.
import Link from "next/link";
import { useState } from "react";

import { useMe } from "@/lib/auth/use-me";

import { buttonClass } from "./ui";

export function AccountMenuClient({
  profileUrl,
  publicAppUrl,
}: {
  profileUrl: string;
  publicAppUrl: string;
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
            <a
              href={profileUrl}
              data-testid="account-menu-profile-link"
              className="px-3 py-2 text-ink hover:bg-paper"
            >
              프로필
            </a>
            <a
              href={publicAppUrl}
              data-testid="account-menu-contests-link"
              className="px-3 py-2 text-ink hover:bg-paper"
            >
              공모전으로 가기
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
