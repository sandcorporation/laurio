"use client";

// 「할 일」 홈의 세 큐 건수(#65). ADR-0020이 신원 대기·Seller 대기를 하나로
// 뭉치지 않은 것은 운영자가 어느 쪽을 처리해야 하는지 알아야 하기 때문이다 —
// 여기서 그 구분이 실제로 세 개의 숫자가 된다.
//
// 두 조회를 병렬로 부르고, 하나라도 401(세션 만료)이면 로그인으로 돌려보낸다 —
// 깨진 화면을 보여주는 대신 useSession과 같은 원칙을 따른다. 0건과 조회 실패를
// 반드시 구별한다: 0은 "성공했고 값이 0"이고, 실패는 "값을 모른다"이다 — 둘을
// 하나의 상태로 뭉치면 조회가 죽은 날 아무도 눈치채지 못한 채 이의가 쌓인다.
//
// **건수는 건수로 묻는다**(#149). 예전에는 지급 큐 **목록 셋**을 통째로 받아
// `.length` 를 셌다 — 홈을 한 번 여는 데 `Payout` 테이블을 세 번 긁어 전부
// 직렬화하고 숫자 셋만 남기고 버렸다. 게다가 목록에 페이지네이션이 붙는 순간
// 그 숫자는 「전체」가 아니라 「첫 페이지」가 되어 **조용히 20에서 멈춘다**.
import { useEffect, useState } from "react";

import type { components } from "@codemit/bff-client/schema";

import { bffClient } from "@/lib/bff/client";

import { oldestPendingDays } from "./oldest-pending";

export interface QueueCounts {
  pendingAppeals: number;
  // 홈 표(#427)의 「가장 오래 밀린 것」 — 이의 목록을 이미 받아오는 김에 계산한다.
  // 0건이면 잴 대상이 없으므로 null이다(빈 것과 「모른다」를 구별하는 이 파일의
  // 원칙을 그대로 따른다).
  oldestPendingAppealDays: number | null;
  identityPendingPayouts: number;
  sellerPendingPayouts: number;
  // "transfer"(#57 코드리뷰 2차 지적 1) -- Seller는 이미 READY인데 실이체
  // 자체가 실패/미확정인 Payout. 큐 목록에서 조회하지 않으면 운영자 눈에서
  // 완전히 사라지는 것과 같은 이유로 홈 카드에서도 빼면 안 된다.
  transferPendingPayouts: number;
}

export type QueueCountsState =
  | { status: "loading" }
  | { status: "loaded"; counts: QueueCounts }
  | { status: "error" };

type PayoutCounts = components["schemas"]["OperatorPayoutCountsOut"];
type AppealSummary = components["schemas"]["AppealOut"];

interface PendingAppealsSummary {
  count: number;
  oldestDays: number | null;
}

async function pendingAppealsSummary(): Promise<PendingAppealsSummary | null> {
  const result = await bffClient.get<AppealSummary[]>("/api/backend/operator/appeals?status=pending");
  if (!result.ok) return null;
  return { count: result.data.length, oldestDays: oldestPendingDays(result.data.map((a) => a.created_at)) };
}

async function payoutCounts(): Promise<PayoutCounts | null> {
  const result = await bffClient.get<PayoutCounts>("/api/backend/operator/payouts/counts");
  return result.ok ? result.data : null;
}

/** `enabled`가 true가 될 때까지(세션이 확인될 때까지) 조회를 미룬다 — 세션이
 * 없는 상태에서 먼저 401을 만나 화면이 잠깐 깜빡이는 것을 막는다. */
export function useQueueCounts(enabled: boolean): QueueCountsState {
  const [state, setState] = useState<QueueCountsState>({ status: "loading" });

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    // 401(세션 만료)이면 클라이언트가 로그인으로 보낸다(#148) — 여기서는 「값을 모른다」로만
    // 남는다. 0건과 조회 실패를 반드시 구별한다: 0은 "성공했고 값이 0"이고, 실패는 "값을
    // 모른다"이다 — 둘을 하나로 뭉치면 조회가 죽은 날 아무도 눈치채지 못한 채 이의가 쌓인다.
    void Promise.all([pendingAppealsSummary(), payoutCounts()]).then(([appeals, payouts]) => {
      if (cancelled) return;
      if (appeals === null || payouts === null) {
        setState({ status: "error" });
        return;
      }
      setState({
        status: "loaded",
        counts: {
          pendingAppeals: appeals.count,
          oldestPendingAppealDays: appeals.oldestDays,
          identityPendingPayouts: payouts.identity,
          sellerPendingPayouts: payouts.seller,
          transferPendingPayouts: payouts.transfer,
        },
      });
    });

    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return state;
}
