"use client";

// 지급 큐(#68, #422 — 골간으로 옮긴다) — ADR-0020이 갈라 둔 대기(신원·셀러·
// 이체)를 운영자가 넓은 표로 훑는 화면. 시안 `docs/design/operator/
// Payouts.dc.html`의 골간(좌측 내비·상단 바·표·중립 배지)을 그대로 쓴다 —
// 픽셀이 아니라 조각을 옮긴다.
//
// **두 대기 모두 실패가 아니다.** 그래서 이 화면 어디에도 오류·경고 색이나
// role="alert"를 배지에 쓰지 않는다 — role="alert"는 조회 자체가 실패했을
// 때(payout-queue-error)에만 쓴다. 「무엇을 기다리나」(중립 배지)와 「누구
// 차례」(글자)를 분리한 것이 예전 화면과 다른 점이다 — `lib/payouts/
// payout-waiting.ts`가 그 문구를 순수 함수로 낸다.
//
// 색인 대상이 아니므로(ADR-0021) 클라이언트 컴포넌트로 둔다 — operator/app/page.tsx
// 와 같은 판단.
import { Suspense, useState } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";

import { Badge } from "@/app/components/badge";
import { PageHeader } from "@/app/components/page-header";
import { useSession } from "@/lib/auth/use-session";
import { daysWaitingLabel, waitingBadgeLabel, whoseTurn } from "@/lib/payouts/payout-waiting";
import { retryPayoutForOperator } from "@/lib/payouts/actions";
import {
  usePayoutQueue,
  type BlockedOnFilter,
  type OperatorPayoutRow,
} from "@/lib/payouts/use-payout-queue";

function parseFilter(value: string | null): BlockedOnFilter {
  if (value === "identity" || value === "seller" || value === "transfer") return value;
  return "all";
}

const COL = {
  contest: "w-[72px]",
  developer: "w-[120px]",
  amount: "w-[120px]",
  waiting: "w-[96px]",
  turn: "w-[220px]",
  action: "w-[64px]",
};

function TableHead() {
  return (
    <div className="flex gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30">
      <div className={COL.contest}>공모전</div>
      <div className="min-w-0 flex-1">받는 사람</div>
      <div className={`${COL.amount} shrink-0`}>금액</div>
      <div className={`${COL.waiting} shrink-0`}>무엇을 기다리나</div>
      <div className={`${COL.turn} shrink-0`}>누구 차례</div>
      <div className={`${COL.action} shrink-0`}></div>
    </div>
  );
}

function PayoutRow({
  payout,
  zebra,
  onRetried,
}: {
  payout: OperatorPayoutRow;
  zebra: boolean;
  onRetried: () => void;
}) {
  const blockedOn = payout.blocked_on;
  return (
    <div
      data-testid={`payout-row-${payout.idempotency_key}`}
      data-blocked-on={blockedOn ?? ""}
      className={`flex items-center gap-3.5 border-b border-rule px-4 py-2.5 text-[13px] ${
        zebra ? "bg-ink/[2%]" : ""
      }`}
    >
      <div className={`${COL.contest} shrink-0 truncate font-mono text-[13px]`} data-testid="payout-row-contest">
        #{payout.contest_id}
      </div>
      <div className="min-w-0 flex-1 truncate" data-testid="payout-row-developer">
        개발자 #{payout.developer_user_id}
      </div>
      <div className={`${COL.amount} shrink-0 truncate text-right font-mono`} data-testid="payout-row-amount">
        {payout.net_amount.toLocaleString("ko-KR")}원
      </div>
      <div className={`${COL.waiting} shrink-0`}>
        {blockedOn && (
          <Badge testId={`payout-blocked-badge-${blockedOn}`}>{waitingBadgeLabel(blockedOn)}</Badge>
        )}
      </div>
      <div className={`${COL.turn} shrink-0 truncate text-[12.5px] text-ink/62`} data-testid="payout-row-turn">
        {blockedOn && (
          <>
            {whoseTurn(blockedOn, payout.seller_registration_status, payout.operator_actionable)} ·{" "}
            {daysWaitingLabel(payout.created_at)}
          </>
        )}
      </div>
      <div className={`${COL.action} shrink-0`}>
        {/* Operator 의 차례인 행에만 뜬다(`operator_actionable`, 서버가 판정한다, #182) —
            그 밖(UNKNOWN 포함)에는 뜨지 않는다. 실제 행동은 기존 도메인 경로
            (수취인 재등록·실이체 재시도)를 그대로 탄다. */}
        {payout.operator_actionable ? (
          <RetryButton idempotencyKey={payout.idempotency_key} onRetried={onRetried} />
        ) : null}
      </div>
    </div>
  );
}

function RetryButton({
  idempotencyKey,
  onRetried,
}: {
  idempotencyKey: string;
  onRetried: () => void;
}) {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function handleClick() {
    setPending(true);
    setMessage(null);
    const result = await retryPayoutForOperator(idempotencyKey);
    if (result.ok) {
      onRetried();
      return;
    }
    setMessage(result.message);
    setPending(false);
  }

  return (
    <span data-testid={`payout-retry-${idempotencyKey}`} className="flex flex-col gap-1">
      <button
        type="button"
        onClick={handleClick}
        disabled={pending}
        data-testid="payout-retry-submit"
        className="border border-rule bg-surface px-2.5 py-1 text-[12px] text-ink disabled:opacity-50"
      >
        {pending ? "진행 중" : "진행"}
      </button>
      {message ? (
        <span role="alert" data-testid="payout-retry-error" className="text-[11px] text-attention">
          {message}
        </span>
      ) : null}
    </span>
  );
}

function FilterTabs({ filter, onSelect }: { filter: BlockedOnFilter; onSelect: (next: BlockedOnFilter) => void }) {
  const tabs: { value: BlockedOnFilter; label: string }[] = [
    { value: "all", label: "전체" },
    { value: "identity", label: "신원 대기" },
    { value: "seller", label: "셀러 대기" },
    { value: "transfer", label: "이체 대기" },
  ];

  return (
    <nav data-testid="payout-filters" className="flex gap-2">
      {tabs.map((tab) => {
        const active = filter === tab.value;
        return (
          <button
            key={tab.value}
            type="button"
            data-testid={`payout-filter-${tab.value}`}
            aria-current={active ? "true" : undefined}
            onClick={() => onSelect(tab.value)}
            className={`border px-3 py-1.5 text-[12.5px] ${
              active ? "border-ink bg-ink text-paper" : "border-rule bg-surface text-ink"
            }`}
          >
            {tab.label}
          </button>
        );
      })}
    </nav>
  );
}

function PayoutQueueContent() {
  const session = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const filter = parseFilter(searchParams.get("blocked_on"));
  // 운영자가 막힌 지급을 진행시킨 뒤 큐를 다시 읽는다(#182) — 그 행이 실제로
  // 바뀌었는지(문구가 바뀌거나 큐에서 사라지는지)를 새로 고침 없이 보여준다.
  const [refreshNonce, setRefreshNonce] = useState(0);
  const queue = usePayoutQueue(filter, session.status === "authenticated", refreshNonce);
  const refetchAfterRetry = () => setRefreshNonce((current) => current + 1);

  function selectFilter(next: BlockedOnFilter) {
    if (next === "all") {
      router.push(pathname);
    } else {
      router.push(`${pathname}?blocked_on=${next}`);
    }
  }

  if (session.status === "loading") {
    return (
      <div className="p-8">
        <p data-testid="session-loading">불러오는 중...</p>
      </div>
    );
  }

  if (session.status === "unauthenticated") {
    // useSession이 이미 /login으로 보내는 중이다 — 리다이렉트가 붙기 전 한
    // 프레임 동안 보호된 내용이 그려지지 않도록 여기서 아무것도 렌더하지 않는다.
    return null;
  }

  return (
    <>
      <PageHeader
        crumb="할 일 · 지급"
        title="지급 큐"
        description="대기는 실패가 아니다 — 누구 차례인지가 이 표의 핵심이다."
      />
      <div className="flex flex-1 flex-col gap-4 p-8">
        <FilterTabs filter={filter} onSelect={selectFilter} />

        {queue.status === "loading" && <p data-testid="payout-queue-loading">불러오는 중...</p>}

        {queue.status === "error" && (
          <p role="alert" data-testid="payout-queue-error">
            지급 큐를 불러오지 못했습니다. 다시 시도해주세요.
          </p>
        )}

        {queue.status === "ready" && queue.rows.length === 0 && (
          <p data-testid="payout-queue-empty">막혀 있는 지급이 없습니다.</p>
        )}

        {queue.status === "ready" && queue.rows.length > 0 && (
          <>
            {/* **전체 건수를 화면에 적는다**(#149). */}
            <p data-testid="payout-queue-total" className="text-[12.5px] text-ink/62">
              막혀 있는 지급 <strong data-testid="payout-queue-total-count">{queue.count}</strong>건
              (이 화면에 {queue.rows.length}건 표시)
            </p>

            <div data-testid="payout-queue-list" className="border border-rule bg-surface">
              <TableHead />
              {queue.rows.map((payout, i) => (
                <PayoutRow
                  key={payout.idempotency_key}
                  payout={payout}
                  zebra={i % 2 === 1}
                  onRetried={refetchAfterRetry}
                />
              ))}
            </div>

            {/* 목록은 페이지네이션된다(#149). */}
            {queue.hasMore ? (
              <button
                type="button"
                onClick={queue.loadMore}
                disabled={queue.loadingMore}
                data-testid="payout-queue-load-more"
                className="w-fit border border-rule bg-surface px-3 py-1.5 text-[12.5px] text-ink disabled:opacity-50"
              >
                {queue.loadingMore
                  ? "불러오는 중..."
                  : `더 보기 (${queue.rows.length} / ${queue.count})`}
              </button>
            ) : null}
          </>
        )}
      </div>
    </>
  );
}

export default function PayoutQueuePage() {
  return (
    <Suspense fallback={null}>
      <PayoutQueueContent />
    </Suspense>
  );
}
