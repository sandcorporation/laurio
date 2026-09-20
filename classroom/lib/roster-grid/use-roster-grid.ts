"use client";

// 참여자 × 문제 격자 상태 (#290). 남의 클래스는 백엔드가 404를 준다 — 클래스
// 상세·참여자 명단과 같은 이유로 "클래스를 찾을 수 없습니다"로 보여준다.
// 공유 클라이언트 위에 선다(#462).
import { useCallback, useMemo } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { RosterGrid } from "./api";

export type RosterGridState =
  | { status: "loading" }
  | { status: "notFound" }
  | { status: "error" }
  | { status: "ready"; grid: RosterGrid };

const NOT_FOUND = Symbol("roster-grid-not-found");

export function useRosterGrid(classId: number) {
  const { state: queryState, reload: refetch } = useBackendQuery<RosterGrid | typeof NOT_FOUND>(
    bffClient,
    `/api/backend/classroom/classes/${classId}/roster-grid`,
    { onFailure: (failure) => (failure.status === 404 ? NOT_FOUND : undefined) },
  );
  // `refetch-keeps-screen.test.ts`가 이 이름의 로컬 선언을 찾는다.
  const reload = useCallback(() => {
    refetch();
  }, [refetch]);

  // useMemo 없이 매 렌더 새 객체를 만들면 이 값을 effect 의존성으로 쓰는
  // 호출부가 폭주할 수 있다(#462 코드 리뷰).
  const state: RosterGridState = useMemo(
    () =>
      queryState.status === "loading"
        ? { status: "loading" }
        : queryState.status === "error"
          ? { status: "error" }
          : queryState.data === NOT_FOUND
            ? { status: "notFound" }
            : { status: "ready", grid: queryState.data },
    [queryState],
  );

  return { state, reload };
}
