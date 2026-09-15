"use client";

// 「운영팀 알림」 화면(#418, CONTEXT.md 「운영자 알림」) — 계정 검색 → 작성 → 확인 →
// 보내기, 그리고 발송 이력. categories/page.tsx와 같은 분기 순서(#69 함정)를 따른다:
// session.status === "unauthenticated"를 로딩 게이트보다 먼저 검사한다.
//
// 무료 공모전 수상자 옆(#420)에서 이 화면으로 들어오면 쿼리에 받는 사람이 실려
// 있다(`lib/free-contests/notify-link.ts`) — 검색 없이 바로 작성 단계로 시작한다
// (`lib/notifications/recipient-from-query.ts`).
import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";

import { useSession } from "@/lib/auth/use-session";
import { useOperatorNotices } from "@/lib/notifications/use-operator-notices";
import { SendOperatorNoticeForm } from "@/lib/notifications/send-form";
import { OperatorNoticeHistoryTable } from "@/lib/notifications/history-table";
import { recipientFromSearchParams } from "@/lib/notifications/recipient-from-query";

function OperatorNotificationsPageInner() {
  const session = useSession();
  const router = useRouter();
  const searchParams = useSearchParams();
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

  const initialRecipient = recipientFromSearchParams(searchParams);

  return (
    <main>
      <h1 data-testid="operator-notices-heading">운영팀 알림</h1>

      <SendOperatorNoticeForm
        initialRecipient={initialRecipient}
        onSent={reload}
        onSessionExpired={handleSessionExpired}
      />

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

export default function OperatorNotificationsPage() {
  // useSearchParams는 Suspense 경계가 필요하다(operator/app/appeals/page.tsx와
  // 같은 이유).
  return (
    <Suspense fallback={null}>
      <OperatorNotificationsPageInner />
    </Suspense>
  );
}
