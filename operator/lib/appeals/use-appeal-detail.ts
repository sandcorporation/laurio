"use client";

// 이의 상세(#66). 존재하지 않는 이의는 "없다"고 말해야 하고(빈 상세를 그리지
// 않는다), 그건 "불러오지 못했습니다"(그 외 실패)와 다른 상태다 — 목록의
// 빈 목록/실패 구분과 같은 원칙을 상세에도 적용한다.
import { useEffect, useState } from "react";

import { bffClient } from "@/lib/bff/client";

import type { AppealDetail } from "./types";

export type AppealDetailState =
  | { status: "loading" }
  | { status: "redirecting" }
  | { status: "loaded"; appeal: AppealDetail }
  | { status: "not-found" }
  | { status: "error" };

export function useAppealDetail(appealId: string, enabled: boolean): AppealDetailState {
  const [state, setState] = useState<AppealDetailState>({ status: "loading" });

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setState({ status: "loading" });

    void bffClient.get<AppealDetail>(`/api/backend/operator/appeals/${appealId}`).then((result) => {
      if (cancelled) return;
      if (result.ok) {
        setState({ status: "loaded", appeal: result.data });
        return;
      }
      if (result.code === "unauthorized") {
        // 이동을 시작하기 전에 먼저 상태를 바꾼다 — "불러오는 중..."에 갇히지 않는다.
        setState({ status: "redirecting" });
        return;
      }
      setState(result.status === 404 ? { status: "not-found" } : { status: "error" });
    });

    return () => {
      cancelled = true;
    };
  }, [appealId, enabled]);

  return state;
}
