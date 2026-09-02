"use client";

// 「할 일」 홈의 세 큐 건수(#65). ADR-0020이 신원 대기·Seller 대기를 하나로
// 뭉치지 않은 것은 운영자가 어느 쪽을 처리해야 하는지 알아야 하기 때문이다 —
// 여기서 그 구분이 실제로 세 개의 숫자가 된다.
//
// 세 조회를 병렬로 부르고, 하나라도 401(세션 만료)이면 로그인으로 돌려보낸다 —
// 깨진 화면을 보여주는 대신 useSession과 같은 원칙을 따른다. 0건과 조회 실패를
// 반드시 구별한다: 0은 "성공했고 값이 0"이고, 실패는 "값을 모른다"이다 — 둘을
// 하나의 상태로 뭉치면 조회가 죽은 날 아무도 눈치채지 못한 채 이의가 쌓인다.
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export interface QueueCounts {
  pendingAppeals: number;
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

async function countFrom(path: string): Promise<{ status: number; count: number | null }> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) return { status: res.status, count: null };
  const body = (await res.json()) as unknown;
  return { status: res.status, count: Array.isArray(body) ? body.length : null };
}

/** `enabled`가 true가 될 때까지(세션이 확인될 때까지) 조회를 미룬다 — 세션이
 * 없는 상태에서 먼저 401을 만나 화면이 잠깐 깜빡이는 것을 막는다. */
export function useQueueCounts(enabled: boolean): QueueCountsState {
  const router = useRouter();
  const [state, setState] = useState<QueueCountsState>({ status: "loading" });

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    async function load() {
      try {
        const [appeals, identity, seller, transfer] = await Promise.all([
          countFrom("/api/backend/operator/appeals?status=pending"),
          countFrom("/api/backend/operator/payouts?blocked_on=identity"),
          countFrom("/api/backend/operator/payouts?blocked_on=seller"),
          countFrom("/api/backend/operator/payouts?blocked_on=transfer"),
        ]);
        if (cancelled) return;

        if ([appeals.status, identity.status, seller.status, transfer.status].includes(401)) {
          router.replace("/login");
          return;
        }

        if (
          appeals.count === null ||
          identity.count === null ||
          seller.count === null ||
          transfer.count === null
        ) {
          setState({ status: "error" });
          return;
        }

        setState({
          status: "loaded",
          counts: {
            pendingAppeals: appeals.count,
            identityPendingPayouts: identity.count,
            sellerPendingPayouts: seller.count,
            transferPendingPayouts: transfer.count,
          },
        });
      } catch {
        if (!cancelled) setState({ status: "error" });
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [enabled, router]);

  return state;
}
