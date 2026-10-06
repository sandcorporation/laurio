"use client";

// 예상 채점 비용 상태 (#591). 「클래스 설정 › 채점」과 「문제 설정 › 채점 모델」이 함께
// 쓴다 — `problemId` 를 주면 그 문제의 지난 시도부터 기준으로 삼는다.
import { useMemo } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { ScoringCostEstimate } from "./cost";

export type ScoringCostState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; estimate: ScoringCostEstimate };

export function useScoringCost(classId: number, problemId?: number): ScoringCostState {
  const path =
    problemId === undefined
      ? `/api/backend/classroom/classes/${classId}/scoring-cost`
      : `/api/backend/classroom/classes/${classId}/scoring-cost?problem_id=${problemId}`;
  const { state } = useBackendQuery<ScoringCostEstimate>(bffClient, path);
  return useMemo(
    () =>
      state.status === "loading"
        ? { status: "loading" }
        : state.status === "error"
          ? { status: "error" }
          : { status: "ready", estimate: state.data },
    [state],
  );
}
