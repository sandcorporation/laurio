"use client";

// 강사가 보는 제출 현황 상태 (#291). 강사 본인의 클래스가 아니거나 문제를
// 찾을 수 없으면 백엔드가 404를 준다 — `use-my-problem.ts`와 같은 이유로 그
// 사실을 "notFound"로 구별한다.
import { useCallback, useEffect, useState } from "react";

import { BackendError } from "@/lib/backend/client";

import { fetchProblemSubmissions, type InstructorSubmissionRow } from "./api";

export type ProblemSubmissionsState =
  | { status: "loading" }
  | { status: "notFound" }
  | { status: "error" }
  | { status: "ready"; submissions: InstructorSubmissionRow[] };

export function useProblemSubmissions(classId: number, problemId: number) {
  const [state, setState] = useState<ProblemSubmissionsState>({ status: "loading" });

  const reload = useCallback(() => {
    setState({ status: "loading" });
    fetchProblemSubmissions(classId, problemId)
      .then((submissions) => setState({ status: "ready", submissions }))
      .catch((error: unknown) => {
        if (error instanceof BackendError && error.status === 404) {
          setState({ status: "notFound" });
        } else {
          setState({ status: "error" });
        }
      });
  }, [classId, problemId]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { state, reload };
}
