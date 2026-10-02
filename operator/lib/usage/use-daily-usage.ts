"use client";

// 날짜별 사용량(#492) — use-reported-templates.ts 와 같은 원칙: 불러오는 중·실패를
// 0 과 다른 상태로 둔다. 422(시작일이 종료일보다 늦다 등)는 서버의 문장을 그대로
// 보인다. 401 은 bffClient 가 로그인으로 보낸다.
import { useEffect, useState } from "react";

import { bffClient } from "@/lib/bff/client";

import { periodQuery, type UsagePeriod } from "./period";
import type { DailyUsage } from "./types";

export type DailyUsageState =
  | { status: "loading" }
  | { status: "redirecting" }
  | { status: "loaded"; usage: DailyUsage }
  | { status: "error"; detail: string };

export function useDailyUsage(period: UsagePeriod, enabled: boolean): DailyUsageState {
  const [state, setState] = useState<DailyUsageState>({ status: "loading" });
  const query = periodQuery(period);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setState({ status: "loading" });

    void bffClient
      .get<DailyUsage>(`/api/backend/operator/classroom/usage/daily${query}`)
      .then((result) => {
        if (cancelled) return;
        if (result.ok) {
          setState({ status: "loaded", usage: result.data });
          return;
        }
        setState(
          result.code === "unauthorized"
            ? { status: "redirecting" }
            : { status: "error", detail: result.detail },
        );
      });

    return () => {
      cancelled = true;
    };
  }, [enabled, query]);

  return state;
}
