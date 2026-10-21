"use client";

// 클래스 상세 「최근 제출」 카드의 상태(#633, 백엔드 #632). 최근 10건 고정, 새것부터. 채점이 끝나면
// (attempt-scored) 다시 읽는다 — 문제 목록의 달성률과 같은 신호다(`use-problems.ts`).
import { useCallback } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";
import { useRealtimeRefresh } from "@/lib/events/use-realtime-refresh";
import { ATTEMPT_SCORED, type StreamEvent } from "@/lib/events/types";

// 격자 칸과 같은 낱말 — 그 시도 하나의 결과다.
export type RecentAttemptStatus = "passed" | "attempted_not_passed" | "scoring" | "needs_setup";

export type RecentAttemptRow = {
  id: number;
  member_id: number;
  member_display_name: string;
  problem_id: number;
  problem_title: string;
  attempt_number: number;
  status: RecentAttemptStatus;
  submitted_at: string;
  // 권장 기한 뒤에 낸 시도인가(#769) — 결과 낱말에 「· 늦음」으로 붙는다(#774).
  late: boolean;
};

const FALLBACK_POLL_MS = 30_000;

export function useRecentAttempts(classId: number) {
  const { state, reload: refetch } = useBackendQuery<RecentAttemptRow[]>(
    bffClient,
    `/api/backend/classroom/classes/${classId}/recent-attempts`,
  );
  // `refetch-keeps-screen.test.ts`가 이 이름의 로컬 선언을 찾는다.
  const reload = useCallback(() => {
    refetch();
  }, [refetch]);
  const matches = useCallback(
    (event: StreamEvent) => event.kind === ATTEMPT_SCORED && event.payload.class_id === classId,
    [classId],
  );
  useRealtimeRefresh({ matches, waiting: true, fallbackPollMs: FALLBACK_POLL_MS, reload });
  return state;
}
