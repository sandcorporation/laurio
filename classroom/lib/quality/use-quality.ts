"use client";

// 완성도 순위(강사)와 본인 완성도(참여자)를 읽는다(#883). 큐에 남은 작업이 있는 동안만 짧게 다시 읽는다.
// 결과가 생기는 대로 표가 채워진다.
import { useCallback, useEffect, useMemo } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import { qualityPath, type MyQuality, type QualityBoard } from "./api";

// grader 는 0.5초 안에 줍는다 — 큐에 남은 동안만 1초마다 다시 읽는다.
const POLL_MS = 1_000;

export function useProblemQuality(classId: number, problemId: number) {
  const { state, reload: refetch } = useBackendQuery<QualityBoard>(bffClient, qualityPath(classId, problemId));
  // `refetch-keeps-screen.test.ts`가 이 이름의 로컬 선언을 찾는다 — 다시 읽어도 그린 표를 비우지 않는다.
  const reload = useCallback(() => {
    refetch();
  }, [refetch]);
  const queued = state.status === "ready" && state.data.queued_count > 0;
  useEffect(() => {
    if (!queued) return;
    const timer = window.setInterval(reload, POLL_MS);
    return () => window.clearInterval(timer);
  }, [queued, reload]);
  return { state, reload };
}

const NOT_PUBLIC = Symbol("quality-not-public");

/** 참여자 본인의 완성도 — 공개가 꺼졌거나 본인 기록이 없으면(404) `null`. */
export function useMyQuality(classId: number, problemId: number, enabled: boolean): MyQuality | null {
  const { state } = useBackendQuery<MyQuality | typeof NOT_PUBLIC>(
    bffClient,
    enabled ? qualityPath(classId, problemId, "/mine") : null,
    { onFailure: (failure) => (failure.status === 404 ? NOT_PUBLIC : undefined) },
  );
  return useMemo(
    () => (state.status === "ready" && state.data !== NOT_PUBLIC ? state.data : null),
    [state],
  );
}
