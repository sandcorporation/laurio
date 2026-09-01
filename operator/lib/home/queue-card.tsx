"use client";

// 「할 일」 홈의 큐 카드 하나(#65). 보는 것과 처리하러 가는 것이 한 동작이어야
// 한다는 인수조건대로, 카드 전체가 그 큐로 가는 링크다 — 건수가 0이어도 마찬가지다
// (걸러 볼 수 있어야 "정말 0인가"를 스스로 확인할 수 있다).
import Link from "next/link";

import type { QueueCountsState } from "./use-queue-counts";

export function QueueCard({
  testId,
  label,
  href,
  state,
  pick,
}: {
  testId: string;
  label: string;
  href: string;
  state: QueueCountsState;
  pick: (counts: { pendingAppeals: number; identityPendingPayouts: number; sellerPendingPayouts: number }) => number;
}) {
  return (
    <Link href={href} data-testid={testId}>
      <p>{label}</p>
      {state.status === "loading" && (
        <span data-testid={`${testId}-loading`}>불러오는 중...</span>
      )}
      {state.status === "error" && (
        <span role="alert" data-testid={`${testId}-error`}>
          불러오지 못했습니다.
        </span>
      )}
      {state.status === "loaded" && pick(state.counts) === 0 && (
        <span data-testid={`${testId}-empty`}>처리할 것이 없습니다.</span>
      )}
      {state.status === "loaded" && pick(state.counts) > 0 && (
        <span data-testid={`${testId}-count`}>{pick(state.counts)}건</span>
      )}
    </Link>
  );
}
