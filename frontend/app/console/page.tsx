"use client";

// 인증 구역 착지 페이지(ADR-0015, FE-07 #32). 로그인 흐름과 미들웨어 가드가
// 실제로 이어지는지 눈으로 볼 수 있는 최소 화면이다 — 실제 대시보드는 이후
// 티켓이 채운다.
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { useSession } from "@/lib/auth/use-session";
import { contestProductEnabled } from "@/lib/contest-switch";
import { PageShell, buttonClass } from "@/app/components/ui";

export default function AppHome() {
  const session = useSession();
  const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);

  async function handleLogout() {
    setLoggingOut(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }

  if (session.status === "loading") {
    return (
      <PageShell>
        <p data-testid="session-loading">불러오는 중...</p>
      </PageShell>
    );
  }

  if (session.status === "unauthenticated") {
    // useSession이 이미 /login으로 보내는 중이다 — 리다이렉트가 붙기 전 한 프레임
    // 동안 보호된 내용이 그려지지 않도록 여기서 아무것도 렌더하지 않는다.
    return null;
  }

  return (
    <PageShell>
      <div className="flex flex-col gap-6">
        <h1 className="text-2xl font-semibold" data-testid="app-home-heading">
          환영합니다, {session.user.username}
        </h1>
        <p className="text-sm text-ink" data-testid="app-home-protected-content">
          이 화면은 로그인해야만 보입니다.
        </p>
        {/* 「내 참가 현황」으로 가는 진입점(#74). 이 링크가 없으면 그 화면은 URL 을
            직접 쳐야만 닿는다 — 운영자 앱의 계정 관리 화면이 실제로 그 상태로
            한 번 나갔다(#69). */}
        <Link
          href="/console/participation"
          data-testid="app-home-participation-link"
          className={`w-fit ${buttonClass("secondary")}`}
        >
          내 참가 현황
        </Link>
        {/* 개최자 쪽 진입점(#81). 참가와 개최는 같은 계정이 둘 다 할 수 있으므로
            둘 다 여기 있다 — 역할로 화면을 가르지 않는다. 공모전 제품
            스위치(#271)가 꺼지면 뺀다 — `/console/contests/**`가 없는 페이지이므로
            그리로 가는 이 진입점도 감춘다. */}
        {contestProductEnabled() && (
          <Link
            href="/console/contests"
            data-testid="app-home-my-contests-link"
            className={`w-fit ${buttonClass("secondary")}`}
          >
            내 공모전
          </Link>
        )}
        {/* 표시 이름·소개를 보고 고치는 화면으로 가는 진입점(#228). 콘솔에서
            찾아갈 수 있어야 한다는 것이 이 티켓의 AC다 — URL을 직접 쳐야만
            닿는 화면을 만들지 않는다("내 참가 현황"·"탈퇴" 링크와 같은 이유). */}
        <Link
          href="/console/profile"
          data-testid="app-home-profile-link"
          className={`w-fit ${buttonClass("secondary")}`}
        >
          내 정보
        </Link>
        <button
          type="button"
          onClick={handleLogout}
          disabled={loggingOut}
          data-testid="logout-button"
          className={`w-fit ${buttonClass("secondary")}`}
        >
          {loggingOut ? "로그아웃 중..." : "로그아웃"}
        </button>
        {/* 탈퇴 진입점(#100, ADR-0025). 클릭 한 번으로 닿아야 한다는 것이 이
            티켓의 인수조건이다 — 링크가 없으면 URL을 직접 쳐야만 닿는 화면이
            된다(「내 참가 현황」 링크가 같은 이유로 여기 있는 것과 같다). */}
        <Link
          href="/console/withdraw"
          data-testid="app-home-withdraw-link"
          className={`w-fit ${buttonClass("danger")}`}
        >
          탈퇴
        </Link>
      </div>
    </PageShell>
  );
}
