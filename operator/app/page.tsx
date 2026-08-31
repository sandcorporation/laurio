"use client";

// 「할 일」 홈(#65). 운영자가 이 앱을 여는 이유는 단 하나 — 자기를 기다리는 것이
// 무엇인지 알기 위해서다. 세 큐의 건수를 보여주고, 각 건수에서 그 목록으로 바로
// 간다. 목록 화면 자체(이의 심판 #66, 지급 큐 #68)는 다른 티켓의 몫이라 여기서는
// 만들지 않는다 — 링크의 목적지로만 남겨 둔다.
import { useState } from "react";
import { useRouter } from "next/navigation";

import { QueueCard } from "@/lib/home/queue-card";
import { useQueueCounts } from "@/lib/home/use-queue-counts";
import { useSession } from "@/lib/auth/use-session";

export default function OperatorHome() {
  const session = useSession();
  const counts = useQueueCounts(session.status === "authenticated");
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

      <section data-testid="operator-home-queues">
        <QueueCard
          testId="queue-appeals-pending"
          label="심판 대기 중인 이의"
          href="/appeals?status=pending"
          state={counts}
          pick={(c) => c.pendingAppeals}
        />
        <QueueCard
          testId="queue-payouts-identity"
          label="신원 대기 중인 지급"
          href="/payouts?blocked_on=identity"
          state={counts}
          pick={(c) => c.identityPendingPayouts}
        />
        <QueueCard
          testId="queue-payouts-seller"
          label="Seller 대기 중인 지급"
          href="/payouts?blocked_on=seller"
          state={counts}
          pick={(c) => c.sellerPendingPayouts}
        />
      </section>

      <button type="button" data-testid="logout-button" onClick={handleLogout} disabled={loggingOut}>
        {loggingOut ? "로그아웃 중..." : "로그아웃"}
      </button>
    </main>
  );
}
