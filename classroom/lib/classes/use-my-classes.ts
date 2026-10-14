"use client";

// 「내 클래스」 목록 상태 (#278). 0건·조회 실패·불러오는 중을 셋으로 구별한다 —
// 같아 보이면 조회가 죽은 날 강사는 자기 클래스가 사라졌다고 읽는다
// (frontend/lib/sponsorship/use-my-contests.ts와 같은 이유). 공유 클라이언트
// 위에 선다(#462) — 401·취소 플래그는 `useBackendQuery`가 소유한다.
import { useMemo } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { ClassRow } from "./api";

export type MyClassesState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; classes: ClassRow[] };

export function useMyClasses(): MyClassesState {
  const { state: queryState } = useBackendQuery<ClassRow[]>(bffClient, "/api/backend/classroom/classes");

  // 돌려주는 객체를 조회 결과가 바뀔 때만 새로 만든다(#462 코드 리뷰). 지금 호출부는
  // 상태 문자열과 `classes`(조회 결과 배열 그대로라 렌더마다 같은 참조다)만 읽어 이것에
  // 기대지 않지만, 바깥 객체를 효과 의존성이나 렌더 중 동일성 비교에 쓰는 호출부가
  // 생기면 매 렌더 새 객체는 그 효과를 매번 다시 돌리거나 그 비교를 매번 참으로 만든다(#697).
  return useMemo<MyClassesState>(() => {
    if (queryState.status === "loading") return { status: "loading" };
    if (queryState.status === "error") return { status: "error" };
    return { status: "ready", classes: queryState.data };
  }, [queryState]);
}
