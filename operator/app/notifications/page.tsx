"use client";

// 「운영팀 알림」 화면(#418, CONTEXT.md 「운영자 알림」, #424 — 골간으로 옮긴다) —
// 받는 사람 → 작성 → 확인 세 단계가 화면에 보이고, 발송 이력은 표로 보인다. 시안
// `docs/design/operator/OperatorNotice.dc.html`의 골간(좌측 내비·상단 바·카드·
// 표)을 그대로 쓴다 — 픽셀이 아니라 조각을 옮긴다. categories/page.tsx와 같은
// 분기 순서(#69 함정)를 따른다: session.status === "unauthenticated"를 로딩
// 게이트보다 먼저 검사한다.
//
// 무료 공모전 수상자 옆(#420)에서 이 화면으로 들어오면 쿼리에 받는 사람이 실려
// 있다(`lib/free-contests/notify-link.ts`) — 검색 없이 바로 작성 단계로 시작한다
// (`lib/notifications/recipient-from-query.ts`).
import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { PageHeader } from "@/app/components/page-header";
import { Panel } from "@/app/components/panel";
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
      <div className="p-8">
        <p data-testid="operator-notices-loading">불러오는 중...</p>
      </div>
    );
  }

  const initialRecipient = recipientFromSearchParams(searchParams);

  return (
    <>
      <PageHeader
        crumb="운영 · 운영팀 알림"
        title="운영팀 알림"
        description="앱 안 알림으로만 간다 — 이미지는 비공개 저장소에 둔다."
      />
      <div className="flex flex-1 flex-col gap-[18px] p-8">
        <div className="flex items-start gap-[18px]">
          <div className="min-w-0 flex-1">
            <SendOperatorNoticeForm
              initialRecipient={initialRecipient}
              onSent={reload}
              onSessionExpired={handleSessionExpired}
            />
          </div>
          <div className="flex w-[380px] shrink-0 flex-col gap-[18px]">
            <Panel title="이 화면의 약속">
              <div className="flex flex-col gap-[9px] px-[15px] py-[14px]">
                <p className="text-[12px] leading-[1.65] text-ink/62">
                  <strong className="font-semibold">이미지는 비공개 저장소에 둔다</strong> — 받는 사람과 보낸 운영자만
                  짧게 유효한 주소를 받습니다. 목록 응답에는 주소가 실리지 않습니다.
                </p>
                <p className="text-[12px] leading-[1.65] text-attention">
                  보낸 뒤에는 고칠 수도 지울 수도 없습니다 — 잘못 보냈으면 새 알림으로 바로잡습니다.
                </p>
                <p className="text-[12px] leading-[1.65] text-ink/45">
                  문자·알림톡으로 가지 않습니다. 앱 안 알림으로만 보입니다.
                </p>
              </div>
            </Panel>
          </div>
        </div>

        <Panel title="발송 이력" meta="최신순 · 고칠 수 없다">
          {state.status === "loading" && (
            <p data-testid="operator-notices-history-loading" className="px-[15px] py-[14px] text-[13px] text-ink/62">
              불러오는 중...
            </p>
          )}
          {state.status === "error" && (
            <p role="alert" data-testid="operator-notices-history-error" className="px-[15px] py-[14px] text-[13px] text-attention">
              이력을 불러오지 못했습니다.
            </p>
          )}
          {state.status === "loaded" && <OperatorNoticeHistoryTable notices={state.notices} />}
        </Panel>
      </div>
    </>
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
