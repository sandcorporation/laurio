"use client";

// 헤더의 「무료 공모전 개최」(#415 후속, ADR-0048). 무료 개최는 운영자가 계정별로
// 켜는 개최 권한이 있어야 열리므로, 권한이 없는 사람에게 버튼을 보여 주면 누르는
// 순간 「권한 없음」 안내만 만난다(2026-09-15 걷기). 그래서 로그인이 확인된 뒤
// 권한을 한 번 물어 켜져 있을 때만 그린다 — 익명 방문자에게는 요청을 만들지
// 않는다(`HeaderSessionZone` 이 세션을 확인한 뒤에만 이 컴포넌트를 부른다, #237).
import Link from "next/link";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";
import { buttonClass } from "@/lib/ui/classnames";

export function FreeContestCta({ refetchKey }: { refetchKey: string }) {
  const { state } = useBackendQuery<unknown>(bffClient, "/api/backend/contests/free/hosting-permission", {
    refetchKey,
  });
  const granted =
    state.status === "ready" &&
    typeof state.data === "object" &&
    state.data !== null &&
    (state.data as { is_granted?: unknown }).is_granted === true;
  if (!granted) return null;

  return (
    <Link
      href="/console/contests/new-free"
      data-testid="header-cta-new-free-contest"
      className={buttonClass("secondary", "sm")}
    >
      무료 공모전 개최
    </Link>
  );
}
