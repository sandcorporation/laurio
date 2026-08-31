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
  // 지금 `state`가 어느 필터에 대한 응답인지를 따로 들고 있는다 — 필터가
  // 바뀐 순간과 useEffect가 실제로 도는 순간 사이에는 한 틱의 간격이 있고,
  // 그 사이에 커밋되는 렌더는 "새 탭 아래 이전 필터의 행"이라는, 이 티켓이
  // 정확히 막으려던 상태를 그대로 화면에 그린다(코드리뷰 지적 — ADR-0020이
  // 두 대기를 갈라 둔 이유가 운영자가 어느 쪽인지 헷갈리지 않게 하는 것인데,
  // 잘못된 라벨 아래 잘못된 행이 한 프레임이라도 보이면 그 혼동이 실제로
  // 일어난 것이다).
  //
  // "Adjusting state when a prop changes"(React) 패턴대로, effect가 아니라
  // 렌더 도중에 곧바로 되돌린다 — 렌더 중 setState는 이 렌더를 화면에 커밋하지
  // 않고 새 값으로 즉시 다시 렌더하므로, "이전 필터의 행 + 새 탭"이라는 조합은
  // 애초에 화면에 그려질 기회가 없다. useEffect에서 처리하면 이미 한 번
  // 커밋된 뒤라 늦다.
  const [committedFilter, setCommittedFilter] = useState(filter);
  if (filter !== committedFilter) {
    setCommittedFilter(filter);
    setState({ status: "loading" });
  }

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
