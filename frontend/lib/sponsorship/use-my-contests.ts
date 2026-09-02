"use client";

// 「내 공모전」 (#81). `GET /api/contests/mine` 을 BFF 프록시로 친다.
//
// 참가자 쪽 `use-my-participation.ts` 의 개최자판이고, 설계 근거도 같다:
// **「다음 행동」은 여기서 파생시키지 않는다.** 서버가 판정해 내려준 값을 그대로
// 쓰고, 여기서 하는 일은 번역뿐이다. 그 표가 생성된 타입의 유니온을 전부
// 덮으므로 값이 하나 늘면 `tsc --noEmit` 이 이 파일에서 빌드타임에 잡는다.
//
// 0건·조회 실패·불러오는 중을 셋으로 구별한다 — "연 게 없다"와 "불러오지
// 못했다"가 같아 보이면, 조회가 죽은 날 개최자는 자기 공모전이 사라졌다고
// 읽는다.
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { sessionFetch } from "@/lib/auth/client-fetch";
import type { components } from "@/lib/api/schema.gen";

export type SponsorNextAction = components["schemas"]["SponsorNextAction"];
export type SponsoredContestRow = components["schemas"]["MySponsoredContestOut"];

export type MyContestsState =
  | { status: "loading" }
  | { status: "error" }
  | {
      status: "ready";
      rows: SponsoredContestRow[];
      count: number;
      /** 아직 안 받은 페이지가 남았는가 — 남았는데 컨트롤이 없으면 그것들은 없는 것이 된다. */
      hasMore: boolean;
      /** 다음 페이지를 이어 붙인다. */
      loadMore: () => void;
      loadingMore: boolean;
    };

export type SponsorActionLabel = {
  text: string;
  /** 「네 차례인가」. 기다리는 것과 해야 하는 것을 화면이 갈라 보여줘야 한다. */
  mine: boolean;
  /** 심사 비교 화면으로 갈 수 있는 단계인가 (그 화면이 보여줄 것이 있는가). */
  canJudge: boolean;
  /** 결제 화면으로 갈 수 있는 단계인가 (#86). canJudge와 같은 이유로 화면이
   * `next_action`을 직접 비교하지 않고 이 표를 거친다 — 새 상태가 생기면
   * `Record<SponsorNextAction, ...>` 타입 오류로 빌드가 깨진다. */
  canPay: boolean;
};

/** 「다음 행동」의 번역표.
 *
 * `Record<SponsorNextAction, ...>` 이므로 **값이 하나 늘면 이 표에서 타입 오류가
 * 난다.** 그것이 이 설계의 목적이다 — 새 상태가 화면에서 조용히 「알 수 없음」이
 * 되지 않는다.
 */
export const SPONSOR_ACTION_LABELS: Record<SponsorNextAction, SponsorActionLabel> = {
  pay_to_publish: {
    text: "결제해야 공개됩니다",
    mine: true,
    canJudge: false,
    canPay: true,
  },
  // 이 화면의 핵심. 지금 고르지 않으면 심사기간이 지나 무응답 배분으로 넘어간다.
  judge_and_award: {
    text: "제출물을 심사하고 선정하세요",
    mine: true,
    canJudge: true,
    canPay: false,
  },
  accept_handover: {
    text: "인수를 확인하세요 — 확인해야 개발자에게 상금이 갑니다",
    mine: true,
    canJudge: false,
    canPay: false,
  },
  awaiting_submissions: {
    text: "제출을 기다리는 중입니다",
    mine: false,
    canJudge: false,
    canPay: false,
  },
  awaiting_scoring: { text: "채점을 기다리는 중입니다", mine: false, canJudge: false, canPay: false },
  // 스토리 40 — #81 이 존재하는 이유. 「늦음」이 아니라 「보류」다.
  awaiting_appeal_ruling: {
    text: "이의 심판이 끝날 때까지 상금 배분이 보류되어 있습니다",
    mine: false,
    canJudge: false,
    canPay: false,
  },
  awaiting_distribution: {
    text: "상금 배분을 기다리는 중입니다",
    mine: false,
    canJudge: false,
    canPay: false,
  },
  awaiting_payout: {
    text: "개발자에게 지급되는 중입니다",
    mine: false,
    canJudge: false,
    canPay: false,
  },
  no_submissions: { text: "제출 없이 마감되었습니다", mine: false, canJudge: false, canPay: false },
  contest_complete: { text: "완료되었습니다", mine: false, canJudge: false, canPay: false },
};


/** 페이지를 이어 받는다.
 *
 * 목록 엔드포인트는 `page_size=20` 으로 페이지네이션된다. 1페이지만 그리면
 * 공모전(또는 참가)이 20개를 넘는 사람은 나머지에 **도달할 길이 없는데**,
 * 빈 상태 판정에 쓰는 `count` 는 전체 건수라 잘렸다는 사실이 화면에 드러나지도
 * 않는다. `-created_at` 정렬이라 잘리는 쪽이 오래된 것들이고, 그중 하나가 「내
 * 차례」면 이 화면이 막으려던 결과가 그대로 일어난다.
 */
export function useMyContests(): MyContestsState {
  const router = useRouter();
  const [phase, setPhase] = useState<"loading" | "error" | "ready" | "more">("loading");
  const [rows, setRows] = useState<SponsoredContestRow[]>([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const response = await sessionFetch(`/api/backend/contests/mine?page=${page}`, {
          cache: "no-store",
        });
        if (cancelled) return;

        if (response.status === 401) {
          router.replace("/login");
          return;
        }
        if (!response.ok) {
          setPhase("error");
          return;
        }

        const body = (await response.json()) as {
          items: SponsoredContestRow[];
          count: number;
        };
        if (cancelled) return;

        // 페이지를 **이어 붙인다.** 갈아끼우면 「더 보기」가 앞 페이지를 지운다.
        setRows((previous) => (page === 1 ? body.items : [...previous, ...body.items]));
        setCount(body.count);
        setPhase("ready");
      } catch {
        if (!cancelled) setPhase("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [router, page]);

  if (phase === "loading") return { status: "loading" };
  if (phase === "error") return { status: "error" };

  return {
    status: "ready",
    rows,
    count,
    hasMore: rows.length < count,
    loadingMore: phase === "more",
    loadMore: () => {
      setPhase("more");
      setPage((current) => current + 1);
    },
  };
}
