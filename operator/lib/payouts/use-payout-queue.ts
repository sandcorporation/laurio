"use client";

// 지급 큐(#68, ADR-0008/0020). `GET /api/operator/payouts?blocked_on=...`가
// 이미 있는 표면을 그대로 부른다 — 이 화면에 백엔드 몫은 없다.
//
// **"전체"도 절대 무필터 조회를 부르지 않는다.** 백엔드가 blocked_on 없이 부르면
// REQUESTED·CONFIRMED·FAILED까지 전부 돌려준다(payouts/api.py의
// list_payouts_for_operator) — 이 큐가 보여줘야 하는 것은 "확정 후 막혀 있는"
// 것뿐이다(#68 AC). 그래서 "전체"는 identity·seller 두 필터를 병렬로 불러 합친
// 결과다 — 홈의 두 카드가 부르는 것과 정확히 같은 두 엔드포인트이므로, 필터를
// identity나 seller로 좁혔을 때 이 목록의 건수가 홈의 그 카드 건수와 항상
// 일치한다(#68 AC).
//
// 0건과 조회 실패를 구별한다 — operator/lib/home/use-queue-counts.ts와 같은 원칙.
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export type BlockedOnFilter = "all" | "identity" | "seller";
export type BlockedOnKind = "identity" | "seller";

export interface OperatorPayoutRow {
  idempotency_key: string;
  contest_id: number;
  developer_user_id: number;
  net_amount: number;
  status: string;
  blocked_on: BlockedOnKind | null;
  seller_status: string | null;
  has_identity: boolean;
  created_at: string;
}

export type PayoutQueueState =
  | { status: "loading" }
  | { status: "loaded"; payouts: OperatorPayoutRow[] }
  | { status: "error" };

async function fetchBlocked(
  kind: BlockedOnKind,
): Promise<{ status: number; rows: OperatorPayoutRow[] | null }> {
  const res = await fetch(`/api/backend/operator/payouts?blocked_on=${kind}`, {
    cache: "no-store",
  });
  if (!res.ok) return { status: res.status, rows: null };
  const body = (await res.json()) as OperatorPayoutRow[];
  return { status: res.status, rows: body };
}

function kindsFor(filter: BlockedOnFilter): BlockedOnKind[] {
  if (filter === "all") return ["identity", "seller"];
  return [filter];
}

/** `enabled`가 true가 될 때까지(세션이 확인될 때까지) 조회를 미룬다 —
 * operator/lib/home/use-queue-counts.ts와 같은 이유. */
export function usePayoutQueue(filter: BlockedOnFilter, enabled: boolean): PayoutQueueState {
  const router = useRouter();
  const [state, setState] = useState<PayoutQueueState>({ status: "loading" });

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setState({ status: "loading" });

    async function load() {
      try {
        const results = await Promise.all(kindsFor(filter).map(fetchBlocked));
        if (cancelled) return;

        if (results.some((r) => r.status === 401)) {
          router.replace("/login");
          return;
        }

        if (results.some((r) => r.rows === null)) {
          setState({ status: "error" });
          return;
        }

        const merged = results.flatMap((r) => r.rows ?? []);
        merged.sort((a, b) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0));
        setState({ status: "loaded", payouts: merged });
      } catch {
        if (!cancelled) setState({ status: "error" });
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [filter, enabled, router]);

  return state;
}
