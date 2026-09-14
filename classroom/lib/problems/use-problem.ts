"use client";

// 문제 하나의 상세 상태 (#282). 편집 화면이 초기값을 채우는 자리다.
import { useEffect, useState } from "react";

import { backendJson } from "@/lib/backend/client";

import type { ProblemRow } from "./api";

export type ProblemDetailState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; problem: ProblemRow };

export function useProblem(classId: number, problemId: number) {
  const [state, setState] = useState<ProblemDetailState>({ status: "loading" });

  function reload() {
    backendJson<ProblemRow>(`/classroom/classes/${classId}/problems/${problemId}`)
      .then((problem) => setState({ status: "ready", problem }))
      .catch(() => setState((prev) => (prev.status === "ready" ? prev : { status: "error" })));
  }

  useEffect(() => {
    // 보고 있는 대상이 바뀔 때만 화면을 비운다 — 다시 불러오기(`reload`)는 새 응답이
    // 올 때까지 이미 그린 화면을 둔다(lib/rendering/refetch-keeps-screen.test.ts).
    setState({ status: "loading" });
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classId, problemId]);

  return { state, reload };
}
