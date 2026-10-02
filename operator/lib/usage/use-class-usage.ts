"use client";

// 클래스 목록(#493) — 클래스 전체 기간의 합계라 기간을 받지 않는다.
// use-daily-usage.ts 와 같은 상태 모양이다.
import { useEffect, useState } from "react";

import { bffClient } from "@/lib/bff/client";

import type { ClassUsage } from "./types";

export type ClassUsageState =
  | { status: "loading" }
  | { status: "redirecting" }
  | { status: "loaded"; classes: ClassUsage[] }
  | { status: "error"; detail: string };

export function useClassUsage(enabled: boolean): ClassUsageState {
  const [state, setState] = useState<ClassUsageState>({ status: "loading" });

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setState({ status: "loading" });

    void bffClient.get<ClassUsage[]>("/api/backend/operator/classroom/usage/classes").then((result) => {
      if (cancelled) return;
      if (result.ok) {
        setState({ status: "loaded", classes: result.data });
        return;
      }
      setState(
        result.code === "unauthorized" ? { status: "redirecting" } : { status: "error", detail: result.detail },
      );
    });

    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return state;
}
