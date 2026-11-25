"use client";

// 「한때 강사였던 클래스」 번호 목록 상태(#1465 2) — 404 안내가 「더 이상 강사가 아닙니다」와 「찾을 수 없습니다」를
// 가르는 데 쓴다. `use-my-classes.ts` 와 같은 이유로 0건·조회 실패·불러오는 중을 셋으로 구별한다.
import { useMemo } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

export type FormerClassesState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; classes: { id: number }[] };

export function useFormerClasses(): FormerClassesState {
  const { state: queryState } = useBackendQuery<{ id: number }[]>(
    bffClient,
    "/api/backend/classroom/classes/former-instructor",
  );
  return useMemo<FormerClassesState>(() => {
    if (queryState.status === "loading") return { status: "loading" };
    if (queryState.status === "error") return { status: "error" };
    return { status: "ready", classes: queryState.data };
  }, [queryState]);
}
