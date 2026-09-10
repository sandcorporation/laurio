"use client";

// 「내 클래스」 목록 상태 (#278). 0건·조회 실패·불러오는 중을 셋으로 구별한다 —
// 같아 보이면 조회가 죽은 날 강사는 자기 클래스가 사라졌다고 읽는다
// (frontend/lib/sponsorship/use-my-contests.ts와 같은 이유).
import { useEffect, useState } from "react";

import { fetchMyClasses, type ClassRow } from "./api";

export type MyClassesState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; classes: ClassRow[] };

export function useMyClasses(): MyClassesState {
  const [state, setState] = useState<MyClassesState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetchMyClasses()
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
