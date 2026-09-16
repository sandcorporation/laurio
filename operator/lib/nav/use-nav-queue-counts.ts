"use client";

// 왼쪽 내비 배지의 건수(#422). 「할 일」 두 항목(이의 심판·지급)은 이미 홈이
// 쓰는 조회(`use-queue-counts.ts`)를 그대로 재사용한다 — AC가 요구하는 "홈이
// 이미 쓰는 큐 카운트 조회를 재사용한다"가 이것이다.
//
// 「신고된 템플릿」은 홈의 훅에 없는 셋째 조회라 **따로 부른다** — 홈의 훅에
// 얹으면 이 조회 하나가 실패했을 때 이의·지급 배지까지 함께 죽는다(홈은 이
// 화면의 몫이 아니므로 그 실패 모드를 홈에 옮기지 않는다).
import { useEffect, useState } from "react";

import { bffClient } from "@/lib/bff/client";
import { useQueueCounts } from "@/lib/home/use-queue-counts";

import type { NavQueueCounts } from "./nav-groups";

export type NavQueueCountsState =
  | { status: "loading" }
  | { status: "loaded"; counts: NavQueueCounts }
  | { status: "error" };

type ReportedTemplatesState =
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

export function useNavQueueCounts(enabled: boolean): NavQueueCountsState {
  const home = useQueueCounts(enabled);
  const [reported, setReported] = useState<ReportedTemplatesState>({ status: "loading" });

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    void reportedTemplatesCount().then((count) => {
      if (cancelled) return;
      setReported(count === null ? { status: "error" } : { status: "loaded", count });
    });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

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
