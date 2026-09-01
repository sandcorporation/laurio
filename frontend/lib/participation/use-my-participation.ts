"use client";

// 「내 참가 현황」 (#74). `GET /api/submissions/mine` 을 BFF 프록시로 친다 —
// 이 화면에 백엔드 몫은 없다.
//
// **「다음 행동」은 여기서 파생시키지 않는다.** 서버가 판정해 내려준 값을 그대로
// 쓴다. 화면이 원시 상태(Contest.status·Score 유무·Award·Appeal·Payout)에서
// 재파생하면, 나중에 새 상태가 생겼을 때 어느 분기에도 안 걸려 조용히 "알 수
// 없음" 이 된다 — 이 저장소가 반복해 겪은 모양이다.
//
// 여기서 하는 일은 **번역**뿐이다: 서버가 준 enum 값을 사람이 읽을 문구와
// 「네 차례인가」로 옮긴다. 그 표가 생성된 타입의 유니온을 전부 덮으므로, 값이
// 하나 늘면 `tsc --noEmit` 이 이 파일에서 빌드타임에 잡는다 — enum 을 고른
// 유일한 근거가 그 안전망이다.
//
// 0건·조회 실패·불러오는 중을 셋으로 구별한다(운영자 앱의 큐 훅과 같은 원칙) —
// "참가한 게 없다" 와 "불러오지 못했다" 가 같아 보이면, 조회가 죽은 날 아무도
// 눈치채지 못한 채 참가자가 자기 상금을 놓친다.
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { sessionFetch } from "@/lib/auth/client-fetch";
import type { components } from "@/lib/api/schema.gen";

export type NextAction = components["schemas"]["NextAction"];
export type ParticipationRow = components["schemas"]["MyParticipationOut"];

export type ParticipationState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; rows: ParticipationRow[]; count: number };

/** 「다음 행동」의 번역표.
 *
 * `Record<NextAction, ...>` 이므로 **값이 하나 늘면 이 표에서 타입 오류가 난다.**
 * 그것이 이 설계의 목적이다 — 새 상태가 화면에서 조용히 "알 수 없음" 이 되지
 * 않는다.
 *
 * `mine` 은 "네 차례인가" 다. 기다리는 것과 해야 하는 것을 화면이 갈라 보여줘야
 * 참가자가 한눈에 "지금 나한테 온 게 있나" 에 답할 수 있다.
 *
 * `payoutStage` 는 "이 상태에서 지급 화면이 보여줄 것이 있는가" 다. 수상하지
 * 않은 사람에게 지급 화면을 링크하면 「지급 요청」 버튼이 보이는데, 눌러 봐야
 * 서버가 거절한다 — 화면이 시키는 대로 했는데 거절당하는 그 모양이다. 이 값을
 * **번역표 안에** 둔 것은 별도의 Set 으로 빼면 새 상태가 생겼을 때 아무도
 * 결정하지 않은 채 조용히 `false` 가 되기 때문이다. 여기 있으면 `Record` 가
 * 빌드타임에 결정을 강제한다.
 */
export type NextActionLabel = { text: string; mine: boolean; payoutStage: boolean };

export const NEXT_ACTION_LABELS: Record<NextAction, NextActionLabel> = {
  awaiting_deadline: { text: "마감을 기다리는 중입니다", mine: false, payoutStage: false },
  awaiting_scoring: { text: "채점을 기다리는 중입니다", mine: false, payoutStage: false },
  awaiting_judging: { text: "발주자의 심사를 기다리는 중입니다", mine: false, payoutStage: false },
  awaiting_appeal_ruling: { text: "이의 심판을 기다리는 중입니다", mine: false, payoutStage: false },
  awaiting_distribution: { text: "상금 배분을 기다리는 중입니다", mine: false, payoutStage: false },
  // 인수 확인 대기부터가 지급 단계다 — 이때부터 금액 내역이 존재하고, 무엇을
  // 기다리는지 지급 화면이 설명할 것이 있다.
  awaiting_handover_release: {
    text: "인수 확인을 기다리는 중입니다",
    mine: false,
    payoutStage: true,
  },
  awaiting_seller_registration: {
    text: "지급대행 등록을 기다리는 중입니다",
    mine: false,
    payoutStage: true,
  },
  can_appeal: { text: "채점 결과에 이의를 제기할 수 있습니다", mine: true, payoutStage: false },
  request_payout: { text: "상금 지급을 요청하세요", mine: true, payoutStage: true },
  submit_tax_identity: {
    text: "세무 처리를 위한 정보를 제출하세요",
    mine: true,
    payoutStage: true,
  },
  not_selected: { text: "선정되지 않았습니다", mine: false, payoutStage: false },
  // 끝난 뒤에도 내역을 다시 볼 수 있어야 한다 — 얼마가 떼였는지 확인할 곳이
  // 여기밖에 없다.
  payout_complete: { text: "지급이 완료되었습니다", mine: false, payoutStage: true },
};

export function useMyParticipation(): ParticipationState {
  const router = useRouter();
  const [state, setState] = useState<ParticipationState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const response = await sessionFetch("/api/backend/submissions/mine", {
          cache: "no-store",
        });
        if (cancelled) return;

        if (response.status === 401) {
          router.replace("/login");
          return;
        }
        if (!response.ok) {
          setState({ status: "error" });
          return;
        }

        const body = (await response.json()) as { items: ParticipationRow[]; count: number };
        if (!cancelled) {
          setState({ status: "ready", rows: body.items, count: body.count });
        }
      } catch {
        if (!cancelled) setState({ status: "error" });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [router]);

  return state;
}
