"use client";

// 클래스 템플릿 하나의 미리보기 상태 (#319) —
// `problem-templates/use-template-preview.ts`와 같은 모양이다. 공유
// 클라이언트 위에 선다(#462).
import { useCallback, useMemo } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { ClassTemplateRow } from "./api";

export type ClassTemplatePreviewState =
  | { status: "loading" }
  | { status: "gone" }
  | { status: "error" }
  | { status: "ready"; template: ClassTemplateRow };

const GONE = Symbol("class-template-gone");

export function useClassTemplatePreview(shareCode: string) {
  const { state: queryState, reload: refetch } = useBackendQuery<ClassTemplateRow | typeof GONE>(
    bffClient,
    `/api/backend/classroom/class-templates/${shareCode}`,
    { onFailure: (failure) => (failure.status === 404 ? GONE : undefined) },
  );
  // `refetch-keeps-screen.test.ts`가 이 이름의 로컬 선언을 찾는다.
  const reload = useCallback(() => {
    refetch();
  }, [refetch]);

  // 호출부(미리보기 화면이 렌더 중 이름 칸을 맞추는 자리)는 안쪽 데이터 객체
  // (`state.template` = `queryState.data`)의 동일성으로 「새로 읽었나」를 가린다 — 바깥
  // `state` 는 오류 플래그가 섞여 비교 대상으로 쓰지 않는다(#675). useMemo 는
  // 바깥 `state` 도 같은 읽기 동안 같은 객체로 남겨 둘 뿐이다(#462 코드 리뷰).
  const state: ClassTemplatePreviewState = useMemo(() => {
    if (queryState.status === "loading") return { status: "loading" };
    if (queryState.status === "error") return { status: "error" };
    if (queryState.data === GONE) return { status: "gone" };
    return { status: "ready", template: queryState.data };
  }, [queryState]);

  return { state, reload };
}
