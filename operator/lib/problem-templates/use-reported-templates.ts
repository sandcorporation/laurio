"use client";

// 신고된 템플릿 큐(#320) — use-appeal-list.ts와 같은 원칙: 0건과 조회 실패를
// 다른 상태로 분리한다. 401은 세션 만료로 보고 로그인으로 돌려보낸다.
import { useEffect, useState } from "react";

import { bffClient } from "@/lib/bff/client";

import type { ReportedTemplate } from "./types";

export type ReportedTemplatesState =
  | { status: "loading" }
  | { status: "redirecting" }
  | { status: "loaded"; templates: ReportedTemplate[] }
  | { status: "error" };

export function useReportedTemplates(enabled: boolean) {
  const [state, setState] = useState<ReportedTemplatesState>({ status: "loading" });
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setState({ status: "loading" });

    void bffClient
      .get<ReportedTemplate[]>("/api/backend/operator/classroom/problem-templates/reported")
      .then((result) => {
        if (cancelled) return;
        if (result.ok) {
          setState({ status: "loaded", templates: result.data });
          return;
        }
        setState(result.code === "unauthorized" ? { status: "redirecting" } : { status: "error" });
      });

    return () => {
      cancelled = true;
    };
  }, [enabled, reloadToken]);

  return { state, reload: () => setReloadToken((t) => t + 1) };
}
