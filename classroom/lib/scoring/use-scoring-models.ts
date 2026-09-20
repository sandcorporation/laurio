"use client";

// 채점 모델 목록 상태 (#285, #401 — 클래스 기준). 「클래스 설정」과 「문제
// 만들기·편집」이 함께 쓴다. 공유 클라이언트 위에 선다(#462).
import { useCallback, useMemo } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { ScoringModelCatalog, ScoringModelRow } from "./api";

export type { ScoringModelRow };

export type ScoringModelsState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; models: ScoringModelRow[]; source: "live" | "fallback"; unavailableReason: "no_api_key" | "fetch_failed" | null };

export function useScoringModels(classId: number): { state: ScoringModelsState; reload: () => void } {
  const { state: queryState, reload: refetch } = useBackendQuery<ScoringModelCatalog>(
    bffClient,
    `/api/backend/classroom/classes/${classId}/scoring-models`,
  );
  // `refetch-keeps-screen.test.ts`가 이 이름의 로컬 선언을 찾는다.
  const reload = useCallback(() => {
    refetch();
  }, [refetch]);

  // useMemo 없이 매 렌더 새 객체를 만들면 이 값을 effect 의존성으로 쓰는
  // 호출부가 폭주할 수 있다(#462 코드 리뷰).
  const state: ScoringModelsState = useMemo(
    () =>
      queryState.status === "loading"
        ? { status: "loading" }
        : queryState.status === "error"
          ? { status: "error" }
          : {
              status: "ready",
              models: queryState.data.models,
              source: queryState.data.source,
              unavailableReason: queryState.data.unavailable_reason,
            },
    [queryState],
  );

  return { state, reload };
}
