"use client";

// 클래스 상세의 문제 목록 상태 (#282). 순서 변경은 낙관적으로 반영하고 실패하면
// 서버 순서로 되돌린다 — 버튼을 눌렀는데 아무 일도 없어 보이는 것보다, 잠깐
// 바뀌었다가 되돌아가는 편이 "실패했다"는 사실을 더 분명히 전달한다. 공유
// 클라이언트 위에 선다(#462).
import { useCallback, useEffect, useMemo, useState } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import { reorderProblems, type ProblemRow } from "./api";

export type ProblemsState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; problems: ProblemRow[]; reorderError: boolean };

export function useProblems(classId: number) {
  const { state: queryState, reload: refetch } = useBackendQuery<ProblemRow[]>(
    bffClient,
    `/api/backend/classroom/classes/${classId}/problems`,
  );
  // `refetch-keeps-screen.test.ts`가 이 이름의 로컬 선언을 찾는다.
  const reload = useCallback(() => {
    refetch();
  }, [refetch]);

  const serverProblems = queryState.status === "ready" ? queryState.data : null;
  // 순서 변경은 응답을 기다리지 않고 먼저 반영한다 — 성공하면 서버가 돌려준
  // 값으로, 실패하면 되돌리기 전 값으로 되돌린다. 새로 불러온 목록(대상
  // 변경 등)이 도착하면 이 자국은 버린다.
  const [override, setOverride] = useState<ProblemRow[] | null>(null);
  const [reorderError, setReorderError] = useState(false);

  // 보고 있는 클래스가 바뀌면 이전 클래스에서 남은 낙관적 자국을 버린다.
  useEffect(() => {
    setOverride(null);
    setReorderError(false);
  }, [classId]);

  const problems = override ?? serverProblems;

  // useMemo 없이 매 렌더 새 객체를 만들면 이 값을 effect 의존성으로 쓰는
  // 호출부가 폭주할 수 있다(#462 코드 리뷰).
  const state: ProblemsState = useMemo(
    () =>
      queryState.status === "loading"
        ? { status: "loading" }
        : queryState.status === "error"
          ? { status: "error" }
          : { status: "ready", problems: problems ?? [], reorderError },
    [queryState, problems, reorderError],
  );

  const move = useCallback(
    async (problemId: number, direction: "up" | "down") => {
      const current = problems;
      if (!current) return;
      const index = current.findIndex((p) => p.id === problemId);
      const swapWith = direction === "up" ? index - 1 : index + 1;
      if (index < 0 || swapWith < 0 || swapWith >= current.length) return;

      const reordered = [...current];
      [reordered[index], reordered[swapWith]] = [reordered[swapWith], reordered[index]];
      setOverride(reordered);
      setReorderError(false);

      const result = await reorderProblems(
        classId,
        reordered.map((p) => p.id),
      );
      if (result.ok) {
        setOverride(result.data);
      } else {
        setOverride(current);
        setReorderError(true);
      }
    },
    [classId, problems],
  );

  return { state, reload, move };
}
