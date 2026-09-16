"use client";

// 신고된 템플릿 건수(#427) — 왼쪽 내비 배지(`lib/nav/use-nav-queue-counts.ts`)가
// 먼저 이 조회를 따로 뒀다: 「할 일」 큐 셋(#421 홈 범위)에 신고된 템플릿이
// 끼면서 이제 홈도 같은 조회가 필요해졌다. `useQueueCounts`에 얹지 않고
// 계속 독립된 훅으로 두는 이유는 그대로다 — 얹으면 이 조회 하나가 실패했을
// 때 이의·지급 건수까지 함께 죽는다(내비가 `useQueueCounts`를 재사용하므로).
// 홈·내비 둘 다 이 훅을 각자 부른다 — 조회가 두 번 나가지만, 그래야 한쪽
// 실패가 다른 쪽을 끌고 내려가지 않는다.
import { useEffect, useState } from "react";

import { bffClient } from "@/lib/bff/client";

export type ReportedTemplatesCountState =
  | { status: "loading" }
  | { status: "loaded"; count: number }
  | { status: "error" };

async function reportedTemplatesCount(): Promise<number | null> {
  const result = await bffClient.get<unknown>(
    "/api/backend/operator/classroom/problem-templates/reported",
  );
  if (!result.ok) return null;
  return Array.isArray(result.data) ? result.data.length : null;
}

export function useReportedTemplatesCount(enabled: boolean): ReportedTemplatesCountState {
  const [state, setState] = useState<ReportedTemplatesCountState>({ status: "loading" });

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    void reportedTemplatesCount().then((count) => {
      if (cancelled) return;
      setState(count === null ? { status: "error" } : { status: "loaded", count });
    });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return state;
}
