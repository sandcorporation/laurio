"use client";

// 참여자의 문제 목록 상태 (#288). 참여자가 아니면 백엔드가 404를 준다 —
// `use-my-problem.ts`와 같은 이유로 "notFound"로 구별한다.
import { useCallback, useEffect, useState } from "react";

import { BackendError } from "@/lib/backend/client";

import { fetchMyProblems, type ProblemListItem } from "./api";

export type MyProblemsState =
  | { status: "loading" }
  | { status: "notFound" }
  | { status: "error" }
  | { status: "ready"; problems: ProblemListItem[] };

export function useMyProblems(classId: number) {
  const [state, setState] = useState<MyProblemsState>({ status: "loading" });

  const reload = useCallback(() => {
    setState({ status: "loading" });
    fetchMyProblems(classId)
      .then((problems) => setState({ status: "ready", problems }))
      .catch((error: unknown) => {
        if (error instanceof BackendError && error.status === 404) {
          setState({ status: "notFound" });
        } else {
          setState({ status: "error" });
        }
      });
  }, [classId]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { state, reload };
}
