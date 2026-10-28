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

// `reload` — 채점 연결이 바뀌면 단가표의 줄(키 종류마다 쓸 수 있는 모델)이 달라지므로 설정 화면이 저장 뒤에 다시 받는다(#801).
export function useScoringCost(
  classId: number,
  problemId?: number,
): ScoringCostState & { reload: () => void } {
  const path =
    problemId === undefined
      ? `/api/backend/classroom/classes/${classId}/scoring-cost`
      : `/api/backend/classroom/classes/${classId}/scoring-cost?problem_id=${problemId}`;
  const { state, reload } = useBackendQuery<ScoringCostEstimate>(bffClient, path);
  return useMemo(
    () =>
      state.status === "loading"
        ? { status: "loading", reload }
        : state.status === "error"
          ? { status: "error", reload }
          : { status: "ready", estimate: state.data, reload },
    [state, reload],
  );
}
