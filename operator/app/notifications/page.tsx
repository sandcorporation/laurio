"use client";

// 「운영팀 알림」 화면(#418, CONTEXT.md 「운영자 알림」) — 계정 검색 → 작성 → 확인 →
// 보내기, 그리고 발송 이력. categories/page.tsx와 같은 분기 순서(#69 함정)를 따른다:
// session.status === "unauthenticated"를 로딩 게이트보다 먼저 검사한다.
import { useRouter } from "next/navigation";
import Link from "next/link";

import { useSession } from "@/lib/auth/use-session";
import { useOperatorNotices } from "@/lib/notifications/use-operator-notices";
import { SendOperatorNoticeForm } from "@/lib/notifications/send-form";
import { OperatorNoticeHistoryTable } from "@/lib/notifications/history-table";

export default function OperatorNotificationsPage() {
  const session = useSession();
  const router = useRouter();
  const { state, reload } = useOperatorNotices(session.status === "authenticated");

  function handleSessionExpired() {
    router.replace("/login");
  }

  if (session.status === "unauthenticated") {
    return null;
  }

  if (session.status === "loading") {
    return (
      <main>
        <p data-testid="operator-notices-loading">불러오는 중...</p>
      </main>
    );
  }

  return (
    <main>
      <h1 data-testid="operator-notices-heading">운영팀 알림</h1>

      <SendOperatorNoticeForm onSent={reload} onSessionExpired={handleSessionExpired} />

      <h2>발송 이력</h2>
      {state.status === "loading" && <p data-testid="operator-notices-history-loading">불러오는 중...</p>}
      {state.status === "error" && (
        <p role="alert" data-testid="operator-notices-history-error">
          이력을 불러오지 못했습니다.
        </p>
      )}
      {state.status === "loaded" && <OperatorNoticeHistoryTable notices={state.notices} />}

      <p>
        <Link href="/" data-testid="operator-notices-back-link">
          홈으로
        </Link>
      </p>
    </main>
  );
}
