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

  // useMemo 없이 매 렌더 새 객체를 만들면 이 값을 effect 의존성으로 쓰는
  // 호출부(미리보기 화면의 이름 초기값 채우기)가 폭주할 수 있다(#462 코드 리뷰).
  const state: ClassTemplatePreviewState = useMemo(() => {
    if (queryState.status === "loading") return { status: "loading" };
    if (queryState.status === "error") return { status: "error" };
    if (queryState.data === GONE) return { status: "gone" };
    return { status: "ready", template: queryState.data };
  }, [queryState]);

  return { state, reload };
}
