"use client";

// 왼쪽 내비 배지의 건수(#422). 「할 일」 두 항목(이의 심판·지급)은 이미 홈이
// 쓰는 조회(`use-queue-counts.ts`)를 그대로 재사용한다 — AC가 요구하는 "홈이
// 이미 쓰는 큐 카운트 조회를 재사용한다"가 이것이다.
//
// 「신고된 템플릿」은 `use-reported-templates-count.ts`를 **따로** 부른다(홈도
// 같은 훅을 자기 몫으로 따로 부른다, #427) — 홈의 큐 조회에 얹으면 이 조회
// 하나가 실패했을 때 이의·지급 배지까지 함께 죽는다.
import { useQueueCounts } from "@/lib/home/use-queue-counts";
import { useReportedTemplatesCount } from "@/lib/home/use-reported-templates-count";

import type { NavQueueCounts } from "./nav-groups";

export type NavQueueCountsState =
  | { status: "loading" }
  | { status: "loaded"; counts: NavQueueCounts }
  | { status: "error" };

export function useNavQueueCounts(enabled: boolean): NavQueueCountsState {
  const home = useQueueCounts(enabled);
  const reported = useReportedTemplatesCount(enabled);

  if (home.status === "loading" || reported.status === "loading") return { status: "loading" };
  if (home.status === "error" || reported.status === "error") return { status: "error" };

  return {
    status: "loaded",
    counts: {
      pendingAppeals: home.counts.pendingAppeals,
      blockedPayouts:
        home.counts.identityPendingPayouts +
        home.counts.sellerPendingPayouts +
        home.counts.transferPendingPayouts,
      reportedTemplates: reported.count,
    },
  };
}
