"use client";

// 클래스 하나의 사용량(#494) — use-daily-usage.ts 와 같은 모양이다. 404(없는
// 클래스)·422(시작일이 종료일보다 늦다 등)는 서버의 문장을 그대로 보인다.
import { useEffect, useState } from "react";

import { bffClient } from "@/lib/bff/client";

import type { ClassUsage } from "./class-usage-types";
import { periodQuery, type UsagePeriod } from "./period";

export type ClassDetailUsageState =
  | { status: "loading" }
  | { status: "redirecting" }
  | { status: "loaded"; usage: ClassUsage }
  | { status: "error"; detail: string };

export function useClassDetailUsage(classId: string, period: UsagePeriod, enabled: boolean): ClassDetailUsageState {
  const [state, setState] = useState<ClassDetailUsageState>({ status: "loading" });
  const query = periodQuery(period);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setState({ status: "loading" });

    void bffClient
      .get<ClassUsage>(`/api/backend/operator/classroom/usage/classes/${encodeURIComponent(classId)}${query}`)
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
  }, [classId, enabled, query]);

  return state;
}
