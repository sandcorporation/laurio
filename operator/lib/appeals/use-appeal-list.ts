"use client";

// 이의 큐(#66) — 기본은 심판 대기(pending)뿐이다("목록은 아카이브가 아니라
// 할 일이다"). use-queue-counts.ts와 같은 원칙: 0건("표시할 이의가 없습니다")과
// 조회 실패("불러오지 못했습니다")를 다른 상태로 분리한다 — 하나로 뭉치면
// 조회가 죽은 날 목록이 그냥 비어 보이고 아무도 눈치채지 못한다. 401은 세션
// 만료로 보고 로그인으로 돌려보낸다.
import { useEffect, useState } from "react";

import { bffClient } from "@/lib/bff/client";

import type { AppealStatus, AppealSummary } from "./types";

export type AppealListState =
  | { status: "loading" }
  | { status: "redirecting" }
  | { status: "loaded"; appeals: AppealSummary[] }
  | { status: "error" };

/** `enabled`가 true가 될 때까지(세션이 확인될 때까지) 조회를 미룬다 —
 * use-queue-counts.ts와 같은 이유. */
export function useAppealList(
  filter: AppealStatus | "all",
  enabled: boolean,
): AppealListState {
  const [state, setState] = useState<AppealListState>({ status: "loading" });

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setState({ status: "loading" });

    const query = filter === "all" ? "" : `?status=${filter}`;
    void bffClient.get<AppealSummary[]>(`/api/backend/operator/appeals${query}`).then((result) => {
      if (cancelled) return;
      if (result.ok) {
        setState({ status: "loaded", appeals: result.data });
        return;
      }
      // 401 은 클라이언트가 로그인으로 보낸다 — 다만 state 를 "loading" 에 남겨두면 내비게이션이
      // 늦거나 실패했을 때 화면이 그 상태에 갇힌다(코드리뷰 지적). 이동과 무관하게 먼저 바꾼다.
      setState(result.code === "unauthorized" ? { status: "redirecting" } : { status: "error" });
    });

    return () => {
      cancelled = true;
    };
  }, [filter, enabled]);

  return state;
}
