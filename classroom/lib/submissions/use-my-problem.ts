"use client";

// 참여자가 보는 문제+시도 목록 상태 (#286). 참여자가 아니거나 문제가 열려
// 있지 않으면 백엔드가 404를 준다 — `use-class.ts`와 같은 이유로 그 사실을
// "notFound"로 구별한다.
import { useCallback, useEffect, useState } from "react";

import { BackendError } from "@/lib/backend/client";

import { fetchMyProblem, type ProblemSubmissions } from "./api";

export type MyProblemState =
  | { status: "loading" }
  | { status: "notFound" }
  | { status: "error" }
  | { status: "ready"; data: ProblemSubmissions };

export function useMyProblem(classId: number, problemId: number) {
  const [state, setState] = useState<MyProblemState>({ status: "loading" });

  const reload = useCallback(() => {
    setState({ status: "loading" });
    fetchMyProblem(classId, problemId)
      .then((data) => setState({ status: "ready", data }))
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
