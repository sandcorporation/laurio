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
  | {
      status: "ready";
      problems: ProblemListItem[];
      // 이름 편집 칸의 초기값과, 그 칸 자체를 숨길지 판단할 신호(#372) — 이
      // 클래스에서 지금 불리는 이름은 `list_my_problems`가 그대로 실어 준다,
      // 비정규화 없이 렌더될 때마다 서버 값을 다시 받는다.
      memberDisplayName: string;
      memberExpelled: boolean;
      archived: boolean;
    };

export function useMyProblems(classId: number) {
  const [state, setState] = useState<MyProblemsState>({ status: "loading" });

  const reload = useCallback(() => {
    setState({ status: "loading" });
    fetchMyProblems(classId)
      .then((response) =>
        setState({
          status: "ready",
          problems: response.problems,
          memberDisplayName: response.member_display_name,
          memberExpelled: response.member_expelled,
          archived: response.archived,
        }),
      )
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
