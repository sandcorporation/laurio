"use client";

// 인증 구역 착지 페이지(ADR-0015, FE-07 #32). 로그인 흐름과 미들웨어 가드가
// 실제로 이어지는지 눈으로 볼 수 있는 최소 화면이다 — 실제 대시보드는 이후
// 티켓이 채운다.
import { useState } from "react";
import { useRouter } from "next/navigation";

import { useSession } from "@/lib/auth/use-session";

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
      <main className="flex min-h-screen items-center justify-center p-10">
        <p data-testid="session-loading">불러오는 중...</p>
      </main>
    );
  }

  if (session.status === "unauthenticated") {
    // useSession이 이미 /login으로 보내는 중이다 — 리다이렉트가 붙기 전 한 프레임
    // 동안 보호된 내용이 그려지지 않도록 여기서 아무것도 렌더하지 않는다.
    return null;
  }

  return (
    <main className="flex min-h-screen flex-col gap-6 p-10">
      <h1 className="text-2xl font-semibold" data-testid="app-home-heading">
        환영합니다, {session.user.username}
      </h1>
      <p className="text-sm text-ink" data-testid="app-home-protected-content">
        이 화면은 로그인해야만 보입니다.
      </p>
      <button
        type="button"
        onClick={handleLogout}
        disabled={loggingOut}
        data-testid="logout-button"
        className="w-fit rounded-sm border border-rule px-4 py-2 text-sm hover:border-ink disabled:opacity-50"
      >
        {loggingOut ? "로그아웃 중..." : "로그아웃"}
      </button>
    </main>
  );
}
