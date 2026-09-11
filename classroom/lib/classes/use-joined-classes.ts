"use client";

// 「내가 참여자로 들어간 클래스」목록 상태 (#328) — `use-my-classes.ts`와 같은
// 이유로 0건·조회 실패·불러오는 중을 셋으로 구별한다.
import { useEffect, useState } from "react";

import { fetchJoinedClasses, type JoinedClassRow } from "./api";

export type JoinedClassesState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; classes: JoinedClassRow[] };

export function useJoinedClasses(): JoinedClassesState {
  const [state, setState] = useState<JoinedClassesState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetchJoinedClasses()
      .then((classes) => {
        if (!cancelled) setState({ status: "ready", classes });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
