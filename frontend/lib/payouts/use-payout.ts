"use client";

// 지급 화면의 데이터 (#74).
//
// **금액은 계산하지 않는다.** 수수료율·원천징수율은 `Payout` 이 만들어질 때
// 스냅샷으로 박혀 있고(payouts/0004_payout_rate_snapshot), 화면이 율을 다시
// 곱하면 정책이 바뀐 날 이미 만들어진 지급의 화면 금액과 실제 송금액이 갈린다.
// 그래서 네 금액을 그대로 받아 그대로 보여준다.
//
// **주민등록번호는 여기 상태로 두지 않는다.** 폼 컴포넌트의 지역 상태로만
// 존재하고 제출 즉시 버려진다 — 훅이 들고 있으면 리렌더 사이에 살아남고,
// 그 훅을 쓰는 다른 화면이 생기면 따라간다.
import { useCallback, useEffect, useState } from "react";

import { sessionFetch } from "@/lib/auth/client-fetch";
import type { components } from "@/lib/api/schema.gen";

export type Payout = components["schemas"]["PayoutOut"];

export type PayoutState =
  | { status: "loading" }
  | { status: "error" }
  /** 아직 지급을 요청하지 않았다 — 요청할 수 있는지는 서버가 판단한다. */
  | { status: "none" }
  | { status: "ready"; payout: Payout };

export function usePayout(contestId: string): { state: PayoutState; reload: () => void } {
  const [state, setState] = useState<PayoutState>({ status: "loading" });
  const [nonce, setNonce] = useState(0);
  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const response = await sessionFetch(`/api/backend/contests/${contestId}/payout`, {
          cache: "no-store",
        });
        if (cancelled) return;

        // 404 는 실패가 아니다 — "아직 요청하지 않았다"는 정상적인 사실이다.
        if (response.status === 404) return setState({ status: "none" });
        if (!response.ok) return setState({ status: "error" });

        setState({ status: "ready", payout: (await response.json()) as Payout });
      } catch {
        if (!cancelled) setState({ status: "error" });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [contestId, nonce]);

  return { state, reload };
}

async function postAndReadDetail(
  path: string,
  body?: unknown,
): Promise<{ ok: true } | { ok: false; message: string }> {
  const response = await sessionFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });

  if (response.ok || response.status === 201) return { ok: true };

  // 서버 문구를 그대로 쓴다 — 화면이 짐작해 다시 쓰면 언젠가 갈라진다.
  const detail = await response
    .json()
    .then((parsed: { detail?: unknown }) =>
      typeof parsed.detail === "string" ? parsed.detail : undefined,
    )
    .catch(() => undefined);
  return { ok: false, message: detail ?? "요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요." };
}

export function requestPayout(contestId: string) {
  return postAndReadDetail(`/api/backend/contests/${contestId}/payout`);
}

/** 주민등록번호를 보낸다. **호출부는 반환 직후 입력값을 버려야 한다.** */
export function submitTaxIdentity(idempotencyKey: string, residentRegistrationNumber: string) {
  return postAndReadDetail(`/api/backend/payouts/${idempotencyKey}/identity`, {
    resident_registration_number: residentRegistrationNumber,
  });
}


/** Seller(지급대행 수취인) 등록을 다시 시도한다 (#74 스토리 31).
 *
 * 지급대행사 쪽의 일시적 실패로 사람이 고객센터를 거쳐야 한다면, 그건 상금이
 * 사라진 것처럼 느껴지는 시간을 늘릴 뿐이다.
 */
export function retrySellerRegistration(idempotencyKey: string) {
  return postAndReadDetail(`/api/backend/payouts/${idempotencyKey}/seller-registration`);
}

/** 토스 셀러 등록(businessType=INDIVIDUAL)의 individual 객체가 요구하는
 * 전화번호를 제출한다(#57 코드리뷰 지적 10 — next_action_message가 "아래에서
 * 제출해주세요"라고 말하는 폼이 실제로 없었다). Payout이 아직 확정되지
 * 않았어도 미리 제출해 둘 수 있다.
 */
export function submitSellerPhone(idempotencyKey: string, phoneNumber: string) {
  return postAndReadDetail(`/api/backend/payouts/${idempotencyKey}/seller-phone`, {
    phone_number: phoneNumber,
  });
}
