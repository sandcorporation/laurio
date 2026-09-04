"use client";

// 지급 큐(#68) — ADR-0020이 갈라 둔 두 대기(CONFIRMED_IDENTITY_PENDING·
// CONFIRMED_SELLER_PENDING)를 운영자가 실제로 구별해서 볼 자리. 그 결정이 서
// 있던 전제("운영자가 그 구별을 볼 수 있다")를 여기서 처음으로 검증한다.
//
// **두 대기 모두 실패가 아니다.** 그래서 이 화면 어디에도 오류·경고 색이나
// role="alert"를 이 두 배지에 쓰지 않는다 — role="alert"는 조회 자체가 실패했을
// 때(payout-queue-error)에만 쓴다. 금액은 원장에 개발자 미지급금으로 남아
// 있고 사라지지 않았다는 사실을 대기로 그린다.
//
// 색인 대상이 아니므로(ADR-0021) 클라이언트 컴포넌트로 둔다 — operator/app/page.tsx
// 와 같은 판단.
import { Suspense } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";

import { useSession } from "@/lib/auth/use-session";
import {
  usePayoutQueue,
  type BlockedOnFilter,
  type BlockedOnKind,
  type OperatorPayoutRow,
} from "@/lib/payouts/use-payout-queue";

function parseFilter(value: string | null): BlockedOnFilter {
  if (value === "identity" || value === "seller" || value === "transfer") return value;
  return "all";
}

// 같은 라벨·같은 색으로 뭉뚱그리지 않는다(#68 AC) — 문구도, 테스트가 읽는
// data-testid·className도 종류마다 갈린다.
// 생성 타입의 `blocked_on` 은 `string` 이다(#148) — 모르는 값이 오면 그 값을 그대로 보여준다.
const BLOCKED_ON_LABEL: Record<BlockedOnKind, string> = {
  identity: "세무 신원 대기 — Laurio 처리 대기",
  seller: "Seller 등록 대기 — 지급대행사 처리 대기",
  // Seller 자체는 이미 READY인데 실이체(벤더 이체 API)만 실패/미확정인
  // 경우다(#57 코드리뷰 2차 지적 1) -- "Seller 등록 대기"라고 부르면 운영자가
  // Seller 쪽을 다시 들여다보게 만드는데, 실제로 해야 할 일은 이체 재시도다.
  transfer: "실이체 대기 — 이체 재시도 필요",
};

function PayoutBadge({ blockedOn }: { blockedOn: string }) {
  return (
    <span
      data-testid={`payout-blocked-badge-${blockedOn}`}
      data-blocked-on={blockedOn}
      className={`badge-waiting badge-waiting-${blockedOn}`}
    >
      {BLOCKED_ON_LABEL[blockedOn as BlockedOnKind] ?? blockedOn}
    </span>
  );
}

function PayoutRow({ payout }: { payout: OperatorPayoutRow }) {
  return (
    <li data-testid={`payout-row-${payout.idempotency_key}`} data-blocked-on={payout.blocked_on ?? ""}>
      <span data-testid="payout-row-contest">콘테스트 #{payout.contest_id}</span>
      <span data-testid="payout-row-developer">개발자 #{payout.developer_user_id}</span>
      <span data-testid="payout-row-amount">{payout.net_amount.toLocaleString("ko-KR")}원</span>
      {payout.blocked_on && <PayoutBadge blockedOn={payout.blocked_on} />}
    </li>
  );
}

function FilterTabs({ filter, onSelect }: { filter: BlockedOnFilter; onSelect: (next: BlockedOnFilter) => void }) {
  const tabs: { value: BlockedOnFilter; label: string }[] = [
    { value: "all", label: "전체" },
    { value: "identity", label: "신원 대기만" },
    { value: "seller", label: "Seller 대기만" },
    { value: "transfer", label: "실이체 대기만" },
  ];

  return (
    <nav data-testid="payout-filters">
      {tabs.map((tab) => (
        <button
          key={tab.value}
          type="button"
          data-testid={`payout-filter-${tab.value}`}
          aria-current={filter === tab.value ? "true" : undefined}
          onClick={() => onSelect(tab.value)}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  );
}

function PayoutQueueContent() {
  const session = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const filter = parseFilter(searchParams.get("blocked_on"));
  const queue = usePayoutQueue(filter, session.status === "authenticated");

  function selectFilter(next: BlockedOnFilter) {
    if (next === "all") {
      router.push(pathname);
    } else {
      router.push(`${pathname}?blocked_on=${next}`);
    }
  }

  if (session.status === "loading") {
    return (
      <main>
        <p data-testid="session-loading">불러오는 중...</p>
      </main>
    );
  }

  if (session.status === "unauthenticated") {
    // useSession이 이미 /login으로 보내는 중이다 — 리다이렉트가 붙기 전 한
    // 프레임 동안 보호된 내용이 그려지지 않도록 여기서 아무것도 렌더하지 않는다.
    return null;
  }

  return (
    <main>
      <h1 data-testid="payout-queue-heading">지급 큐</h1>
      <p data-testid="payout-queue-explainer">
        지급이 확정됐지만 아직 처리되지 않아 대기 중인 목록입니다 — 실패가 아니며, 금액은
        원장에 개발자 미지급금으로 그대로 남아 있습니다.
      </p>

      <FilterTabs filter={filter} onSelect={selectFilter} />

      {queue.status === "loading" && <p data-testid="payout-queue-loading">불러오는 중...</p>}

      {queue.status === "error" && (
        <p role="alert" data-testid="payout-queue-error">
          지급 큐를 불러오지 못했습니다. 다시 시도해주세요.
        </p>
      )}

      {queue.status === "loaded" && queue.payouts.length === 0 && (
        <p data-testid="payout-queue-empty">막혀 있는 지급이 없습니다.</p>
      )}

      {queue.status === "loaded" && queue.payouts.length > 0 && (
        <ul data-testid="payout-queue-list">
          {queue.payouts.map((payout) => (
            <PayoutRow key={payout.idempotency_key} payout={payout} />
          ))}
        </ul>
      )}
    </main>
  );
}

export default function PayoutQueuePage() {
  return (
    <Suspense fallback={null}>
      <PayoutQueueContent />
    </Suspense>
  );
}
