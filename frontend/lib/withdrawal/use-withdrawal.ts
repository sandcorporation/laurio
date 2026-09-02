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
import { useEffect, useState } from "react";

import { sessionFetch } from "@/lib/auth/client-fetch";
import type { components } from "@/lib/api/schema.gen";

export type WithdrawalBlockReason = components["schemas"]["WithdrawalBlockReason"];
export type WithdrawalEligibility = components["schemas"]["WithdrawalEligibilityOut"];

export const BLOCK_REASON_LABELS: Record<WithdrawalBlockReason, string> = {
  sponsor_contest_in_progress:
    "진행 중인(심사가 끝나지 않은) Contest가 있습니다 — 심사가 끝난 뒤 다시 시도해주세요.",
  developer_payout_in_progress:
    "지급이 끝나지 않은 Payout이 있습니다 — 지급이 끝난 뒤 다시 시도해주세요.",
  retention_not_yet_supported:
    "거래 이력이 있는 계정의 탈퇴는 아직 지원되지 않습니다.",
};

export type WithdrawalEligibilityState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; eligibility: WithdrawalEligibility };

export function useWithdrawalEligibility(): WithdrawalEligibilityState {
  const [state, setState] = useState<WithdrawalEligibilityState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const response = await sessionFetch("/api/backend/accounts/withdrawal", {
          cache: "no-store",
        });
        if (cancelled) return;
        if (!response.ok) {
          setState({ status: "error" });
          return;
        }
        const eligibility = (await response.json()) as WithdrawalEligibility;
        setState({ status: "ready", eligibility });
      } catch {
        if (!cancelled) setState({ status: "error" });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}

export type WithdrawalResult =
  | { ok: true; withdrawn_at: string }
  | { ok: false; blockingReasons: WithdrawalBlockReason[]; message: string };

/** 탈퇴를 실제로 실행한다. 유예 없이 즉시 반영된다(ADR-0025). */
export async function executeWithdrawal(): Promise<WithdrawalResult> {
  const response = await sessionFetch("/api/backend/accounts/withdrawal", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });

  if (response.status === 200) {
    const body = (await response.json()) as components["schemas"]["WithdrawalOut"];
    return { ok: true, withdrawn_at: body.withdrawn_at };
  }

  if (response.status === 409) {
    const body = (await response.json()) as components["schemas"]["WithdrawalRejectedOut"];
    return { ok: false, blockingReasons: body.blocking_reasons, message: body.detail };
  }

  return {
    ok: false,
    blockingReasons: [],
    message: "탈퇴를 처리하지 못했습니다. 잠시 후 다시 시도해주세요.",
  };
}
