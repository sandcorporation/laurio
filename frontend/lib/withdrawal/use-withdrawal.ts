"use client";

// 탈퇴 화면 (#100, ADR-0025) — `GET /api/accounts/withdrawal`을 BFF 프록시로
// 쳐서 「막고 있는 것」을 그대로 보여주고, 확인하면 `POST`로 실행한다.
//
// **판정은 여기서 다시 하지 않는다.** Contest 상태·Payout 상태에서 화면이
// 재파생하면 새 상태가 하나 생겼을 때 어느 분기에도 안 걸리고 조용히 사라진다
// — 이 저장소가 반복해 겪은 모양이다(`use-my-participation.ts`와 같은 이유).
// 서버가 내려준 `blocking_reasons`를 번역만 한다.
//
// `BLOCK_REASON_LABELS`가 `Record<WithdrawalBlockReason, string>`인 이유도
// 같다 — 값이 하나 늘면 `tsc --noEmit`이 이 파일에서 빌드타임에 잡는다.
import { normalizeDetail, useBackendQuery } from "@laurio/bff-client";
import type { components } from "@laurio/bff-client/schema";

import { bffClient } from "@/lib/bff/client";

export type WithdrawalBlockReason = components["schemas"]["WithdrawalBlockReason"];
export type WithdrawalEligibility = components["schemas"]["WithdrawalEligibilityOut"];

export const BLOCK_REASON_LABELS: Record<WithdrawalBlockReason, string> = {
  sponsor_contest_in_progress:
    "진행 중인(심사가 끝나지 않은) 공모전이 있습니다 — 심사가 끝난 뒤 다시 시도해주세요.",
  developer_payout_in_progress:
    "지급이 끝나지 않은 지급건이 있습니다 — 지급이 끝난 뒤 다시 시도해주세요.",
};

export type WithdrawalEligibilityState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; eligibility: WithdrawalEligibility };

export function useWithdrawalEligibility(): WithdrawalEligibilityState {
  const { state } = useBackendQuery<WithdrawalEligibility>(
    bffClient,
    "/api/backend/accounts/withdrawal",
  );

  if (state.status === "loading") return { status: "loading" };
  if (state.status === "error") return { status: "error" };
  return { status: "ready", eligibility: state.data };
}


export type WithdrawalResult =
  | { ok: true; withdrawn_at: string }
  | { ok: false; blockingReasons: WithdrawalBlockReason[]; message: string };

/** 탈퇴를 실제로 실행한다. 유예 없이 즉시 반영된다(ADR-0025). */
export async function executeWithdrawal(): Promise<WithdrawalResult> {
  // 409 는 실패이지만 **본문에 막고 있는 것들이 실려 있다** — 화면이 그 목록을 그대로 보여줘야
  // 사용자가 무엇을 끝내야 하는지 안다. 그래서 이 한 곳만 응답 본문을 직접 읽는다(`request` 는
  // 실패에서 detail 만 남긴다).
  const response = await bffClient.fetch("/api/backend/accounts/withdrawal", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });

  if (response.status === 200) {
    const body = (await response.json()) as components["schemas"]["WithdrawalOut"];
    return { ok: true, withdrawn_at: body.withdrawn_at };
  }

  const body = (await response.json().catch(() => null)) as
    | components["schemas"]["WithdrawalRejectedOut"]
    | null;
  return {
    ok: false,
    blockingReasons: body?.blocking_reasons ?? [],
    message: normalizeDetail(body?.detail, "탈퇴를 처리하지 못했습니다. 잠시 후 다시 시도해주세요."),
  };
}
