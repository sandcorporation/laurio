"use client";

// 「내가 참여자로 들어간 클래스」목록 상태 (#328) — `use-my-classes.ts`와 같은
// 이유로 0건·조회 실패·불러오는 중을 셋으로 구별한다. 공유 클라이언트 위에
// 선다(#462).
import { useMemo } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { JoinedClassRow } from "./api";

export type JoinedClassesState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; classes: JoinedClassRow[] };

export function useJoinedClasses(): JoinedClassesState {
  // 본인이 강사인 클래스는 여기 나오지 않는다 — `useMyClasses`가 이미 그
  // 클래스를 「연 것」으로 보여준다(백엔드 `list_joined_classes` docstring).
  const { state: queryState } = useBackendQuery<JoinedClassRow[]>(
    bffClient,
    "/api/backend/classroom/classes/joined",
  );

  // useMemo 없이 매 렌더 새 객체를 만들면 그 객체를 effect 의존성으로 쓰는
  // 호출부가 폭주할 수 있다(#462 코드 리뷰, use-my-classes.ts와 같은 이유).
  return useMemo<JoinedClassesState>(() => {
    if (queryState.status === "loading") return { status: "loading" };
    if (queryState.status === "error") return { status: "error" };
    return { status: "ready", classes: queryState.data };
  }, [queryState]);
}
