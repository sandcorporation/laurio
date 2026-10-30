"use client";

// 운영 지표(#827) — use-daily-usage.ts 와 같은 원칙: 불러오는 중·실패를 0 과 다른 상태로 둔다.
// 401 은 bffClient 가 로그인으로 보낸다.
import { useEffect, useState } from "react";

import { bffClient } from "@/lib/bff/client";

import type { OpsRange } from "./range";
import type { OpsMetrics } from "./types";

export type OpsMetricsState =
  | { status: "loading" }
  | { status: "redirecting" }
  | { status: "loaded"; metrics: OpsMetrics }
  | { status: "error"; detail: string };

export function useOpsMetrics(range: OpsRange, enabled: boolean): OpsMetricsState {
  const [state, setState] = useState<OpsMetricsState>({ status: "loading" });

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setState({ status: "loading" });

    void bffClient.get<OpsMetrics>(`/api/backend/operator/ops-metrics?range=${range}`).then((result) => {
      if (cancelled) return;
      if (result.ok) {
        setState({ status: "loaded", metrics: result.data });
        return;
      }
      setState(result.code === "unauthorized" ? { status: "redirecting" } : { status: "error", detail: result.detail });
    });

    return () => {
      cancelled = true;
    };
  }, [enabled, range]);

  return state;
}
