"use client";

// 지급 큐(#68, ADR-0008/0020). `GET /api/operator/payouts?blocked_on=...`가
// 이미 있는 표면을 그대로 부른다 — 이 화면에 백엔드 몫은 없다.
//
// **「전체」도 요청 하나다**(#149). 예전에는 identity·seller·transfer 셋을 병렬로
// 부른 뒤 응답을 이어 붙이고 **브라우저에서 정렬**했다. 백엔드가 `ORDER BY` 로 매긴
// 순서를 그 자리에서 버리는 셈이었고, 페이지네이션이 붙는 순간엔 아예 틀린다 —
// 세 목록의 1페이지를 합친 것은 합집합의 1페이지가 아니다. 지금은 백엔드가 필터
// 없이도 **막혀 있는 것만** 돌려주므로(`blocked_q`) 「전체」가 그냥 무필터 조회다.
//
// 0건과 조회 실패를 구별한다 — operator/lib/home/use-queue-counts.ts와 같은 원칙.
import { type PagedListState, usePagedList } from "@laurio/bff-client";
import type { components } from "@laurio/bff-client/schema";

import { bffClient } from "@/lib/bff/client";

export type BlockedOnFilter = "all" | "identity" | "seller" | "transfer";
// "transfer"(#57 코드리뷰 2차 지적 1) -- Seller 자체는 이미 READY인데 실이체
// 자체가 실패/미확정인 Payout. CONFIRMED_SELLER_PENDING을 "seller"로만
// 재분류하기 시작한 뒤로 이 값이 실제로 나오기 시작했는데, 이 큐가 그 값을
// 조회하지 않으면 그 행들이 운영자 눈에서 완전히 사라진다.
export type BlockedOnKind = "identity" | "seller" | "transfer";

/** 응답 모양은 생성 타입 그대로다(#148) — 손으로 맞춘 사본을 두지 않는다. */
export type OperatorPayoutRow = components["schemas"]["OperatorPayoutOut"];

export type PayoutQueueState = PagedListState<OperatorPayoutRow>;

function pathFor(filter: BlockedOnFilter): string {
  const base = "/api/backend/operator/payouts";
  return filter === "all" ? base : `${base}?blocked_on=${filter}`;
}

/** `enabled`가 false인 동안(세션이 아직 확인되지 않은 동안)은 조회하지 않는다 —
 * operator/lib/home/use-queue-counts.ts와 같은 이유. 경로가 바뀌면 쌓아 둔 페이지를
 * 버리는 것은 `usePagedList` 가 한다(#149) — 「새 탭 아래 이전 필터의 행」이 한
 * 프레임이라도 보이면 ADR-0020이 두 대기를 갈라 둔 이유가 그 자리에서 무너진다. */
export function usePayoutQueue(filter: BlockedOnFilter, enabled: boolean): PayoutQueueState {
  // 세션 확인 전에는 **경로를 주지 않는다**(#149 코드리뷰) — 반환값만 loading 으로
  // 덮으면 요청은 이미 나간 뒤다. 만료된 세션에서는 그 401 이 세션 조회와 경합해
  // 로그인으로 튕기고, 그렇게 실패한 조회는 `enabled` 가 참이 돼도 다시 시도되지 않는다.
  // **커서 모드다**(#151). 이 큐는 스캔이 60초마다 Payout 을 확정해 계속 머리에 행이
  // 들어온다 — 오프셋이면 운영자가 「더 보기」를 누르는 그 몇 초 사이에 경계가 밀려 같은
  // 행이 두 번 나오고 그 사이 행 하나가 어느 페이지에도 안 나온다.
  return usePagedList<OperatorPayoutRow>(bffClient, enabled ? pathFor(filter) : null, {
    cursor: true,
  });
}
