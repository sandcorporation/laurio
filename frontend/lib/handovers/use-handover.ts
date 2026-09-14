"use client";

// 인수(Handover) 확인 화면의 데이터 (#179, #14, ADR-0004/0005/0014).
//
// Award 직후 양쪽이 정확한 안내를 보는데, 아무도 그 안내를 실행할 길이 없었다 —
// Sponsor는 「내 차례 · 인수를 확인하세요」를 보고도 갈 곳이 없었고, 화면 코드
// 어디에도 `handover` 라는 도메인 이름이 없었다. 이 파일이 그 화면의 데이터를
// 옮긴다.
//
// 호출의 모양(상태기계·401·`detail` 파싱·폴백 문구)은 패키지가 소유한다(#146) —
// `useBackendQuery`에 404를 정상값으로 접어 넣는 방식은 지급 화면
// (`lib/payouts/use-payout.ts`)과 같다.
//
// **낙관적 갱신을 하지 않는다.** 인수 확인은 Escrow 를 해제하는, 되돌릴 수 없는
// 행위다(Award가 「되돌릴 수 없습니다」 확인 단계를 두는 것과 같은 무게, #13).
// 확인됐다고 먼저 그려 놓고 서버가 거절하면 사용자는 자기가 하지 않은 확인을
// 봤다고 믿게 된다 — 서버 응답을 받은 뒤에만 상태를 바꾼다.
import { useBackendQuery } from "@codemit/bff-client";
import type { components } from "@codemit/bff-client/schema";

import { bffClient } from "@/lib/bff/client";

export type Handover = components["schemas"]["HandoverOut"];

export type HandoverPageState =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "forbidden"; message: string }
  | { status: "error" }
  | { status: "ready"; handover: Handover };

const NOT_FOUND = Symbol("handover-not-found");

export function useHandover(contestId: string): {
  state: HandoverPageState;
  reload: () => void;
} {
  const { state, reload } = useBackendQuery<Handover | typeof NOT_FOUND>(
    bffClient,
    `/api/backend/contests/${contestId}/handover`,
    // Award 되지 않은 Contest 는 Handover 자체가 없다 — "없다"는 실패가
    // 아니라 정상적인 사실이다(usePayout의 404 처리와 같은 관용구).
    { onFailure: (failure) => (failure.status === 404 ? NOT_FOUND : undefined) },
  );

  if (state.status === "loading") return { state: { status: "loading" }, reload };
  if (state.status === "error") {
    // "남의 것"과 "못 불러왔다"는 화면이 할 말이 다르다.
    if (state.failure.status === 403) {
      return { state: { status: "forbidden", message: state.failure.detail }, reload };
    }
    return { state: { status: "error" }, reload };
  }
  if (state.data === NOT_FOUND) return { state: { status: "not-found" }, reload };
  return { state: { status: "ready", handover: state.data }, reload };
}

/** Sponsor의 인수 확인 — Escrow를 해제한다. 실패하면 서버 문구를 그대로 돌려준다. */
export async function acceptHandover(
  contestId: string,
): Promise<{ ok: true; handover: Handover } | { ok: false; message: string }> {
  const result = await bffClient.post<Handover>(
    `/api/backend/contests/${contestId}/handover/accept`,
  );
  if (!result.ok) return { ok: false, message: result.detail };
  return { ok: true, handover: result.data };
}
