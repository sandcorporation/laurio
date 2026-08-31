"use client";

// 로그인 후 착지 화면(#63). 지금은 로그인이 실제로 이어지는지 볼 수 있는 최소
// 화면이다 — 자기 아이디·등급을 보여준다. 「할 일」 세 큐 건수는 #65가 이 자리를
// 채운다.
import { useState } from "react";
import { useRouter } from "next/navigation";

import { useSession } from "@/lib/auth/use-session";

export default function OperatorHome() {
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
      <main>
        <p data-testid="session-loading">불러오는 중...</p>
      </main>
    );
  }

  if (session.status === "unauthenticated") {
    // useSession이 이미 /login으로 보내는 중이다 — 리다이렉트가 붙기 전 한
    // 프레임 동안 보호된 내용이 그려지지 않도록 여기서 아무것도 렌더하지 않는다.
    return null;
  }

  return (
    <main>
      <h1 data-testid="operator-home-heading">환영합니다, {session.user.username}</h1>
      <p data-testid="operator-home-grade">
        {session.user.is_superuser ? "상위 등급 (계정 관리 가능)" : "일반 등급"}
      </p>
      <p data-testid="operator-home-protected-content">이 화면은 로그인해야만 보입니다.</p>
      <button type="button" data-testid="logout-button" onClick={handleLogout} disabled={loggingOut}>
        {loggingOut ? "로그아웃 중..." : "로그아웃"}
      </button>
    </main>
  );
}
