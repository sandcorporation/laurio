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

  // useMemo 없이 매 렌더 새 객체를 만들면 이 값의 동일성을 렌더 중에 비교해
  // 기본값을 맞추는 호출부(템플릿 가져오기 화면의 대상 클래스 기본값 등, #691)가
  // 매 렌더 다시 맞추느라 멈추지 않는다(#462 코드 리뷰, #695).
  return useMemo<MyClassesState>(() => {
    if (queryState.status === "loading") return { status: "loading" };
    if (queryState.status === "error") return { status: "error" };
    return { status: "ready", classes: queryState.data };
  }, [queryState]);
}
