"use client";

// 문제 하나의 상세 상태 (#282). 편집 화면이 초기값을 채우는 자리다. 공유
// 클라이언트 위에 선다(#462).
import { useCallback, useMemo } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { ProblemRow } from "./api";

export type ProblemDetailState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; problem: ProblemRow };

export function useProblem(classId: number, problemId: number) {
  const { state: queryState, reload: refetch } = useBackendQuery<ProblemRow>(
    bffClient,
    `/api/backend/classroom/classes/${classId}/problems/${problemId}`,
  );
  // `refetch-keeps-screen.test.ts`가 이 이름의 로컬 선언을 찾는다.
  const reload = useCallback(() => {
    refetch();
  }, [refetch]);

  // useMemo 없이 매 렌더 새 객체를 만들면 그 객체의 동일성으로 「새로 읽었나」를
  // 가리는 호출부(문제 편집 화면이 렌더 중 칸을 맞추는 자리, #675)가 매 렌더 다시
  // 맞춰 무한 렌더 루프로 번진다 — effect 시절에도 실제로 그렇게 났다(#462 코드 리뷰).
  const state: ProblemDetailState = useMemo(
    () =>
      queryState.status === "loading"
        ? { status: "loading" }
        : queryState.status === "error"
          ? { status: "error" }
          : { status: "ready", problem: queryState.data },
    [queryState],
  );

  return { state, reload };
}
