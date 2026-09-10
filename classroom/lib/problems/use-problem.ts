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
    setState({ status: "loading" });
    backendJson<ProblemRow>(`/classroom/classes/${classId}/problems/${problemId}`)
      .then((problem) => setState({ status: "ready", problem }))
      .catch(() => setState({ status: "error" }));
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classId, problemId]);

  return { state, reload };
}
