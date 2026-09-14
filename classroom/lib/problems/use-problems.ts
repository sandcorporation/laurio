"use client";

// 클래스 상세의 문제 목록 상태 (#282). 순서 변경은 낙관적으로 반영하고 실패하면
// 서버 순서로 되돌린다 — 버튼을 눌렀는데 아무 일도 없어 보이는 것보다, 잠깐
// 바뀌었다가 되돌아가는 편이 "실패했다"는 사실을 더 분명히 전달한다.
import { useCallback, useEffect, useState } from "react";

import { fetchProblems, reorderProblems, type ProblemRow } from "./api";

export type ProblemsState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; problems: ProblemRow[]; reorderError: boolean };

export function useProblems(classId: number) {
  const [state, setState] = useState<ProblemsState>({ status: "loading" });

  const reload = useCallback(() => {
    fetchProblems(classId)
      .then((problems) => setState({ status: "ready", problems, reorderError: false }))
      .catch(() => setState((prev) => (prev.status === "ready" ? prev : { status: "error" })));
  }, [classId]);

  useEffect(() => {
    // 보고 있는 대상이 바뀔 때만 화면을 비운다 — 다시 불러오기(`reload`)는 새 응답이
    // 올 때까지 이미 그린 화면을 둔다(lib/rendering/refetch-keeps-screen.test.ts).
    setState({ status: "loading" });
    reload();
  }, [reload]);

  const move = useCallback(
    async (problemId: number, direction: "up" | "down") => {
      if (state.status !== "ready") return;
      const index = state.problems.findIndex((p) => p.id === problemId);
      const swapWith = direction === "up" ? index - 1 : index + 1;
      if (index < 0 || swapWith < 0 || swapWith >= state.problems.length) return;

      const reordered = [...state.problems];
      [reordered[index], reordered[swapWith]] = [reordered[swapWith], reordered[index]];
      setState({ status: "ready", problems: reordered, reorderError: false });

      try {
        const saved = await reorderProblems(
          classId,
          reordered.map((p) => p.id),
        );
        setState({ status: "ready", problems: saved, reorderError: false });
      } catch {
        setState({ status: "ready", problems: state.problems, reorderError: true });
      }
    },
    [classId, state],
  );

  return { state, reload, move };
}
