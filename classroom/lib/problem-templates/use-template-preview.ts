"use client";

// 템플릿 하나의 미리보기 상태 (#316). 로그인은 middleware.ts가 이미
// 보장하므로 `app/join/[code]`의 needsLogin 분기 같은 것이 없다 — 내려간
// 템플릿이면 백엔드가 404를 준다. 공유 클라이언트 위에 선다(#462).
import { useCallback, useMemo } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { ProblemTemplateRow } from "./api";

export type TemplatePreviewState =
  | { status: "loading" }
  | { status: "gone" }
  | { status: "error" }
  | { status: "ready"; template: ProblemTemplateRow };

const GONE = Symbol("problem-template-gone");

export function useTemplatePreview(shareCode: string) {
  const { state: queryState, reload: refetch } = useBackendQuery<ProblemTemplateRow | typeof GONE>(
    bffClient,
    `/api/backend/classroom/problem-templates/${shareCode}`,
    { onFailure: (failure) => (failure.status === 404 ? GONE : undefined) },
  );
  // `refetch-keeps-screen.test.ts`가 이 이름의 로컬 선언을 찾는다.
  const reload = useCallback(() => {
    refetch();
  }, [refetch]);

  // useMemo 없이 매 렌더 새 객체를 만들면 이 값을 effect 의존성으로 쓰는
  // 호출부가 폭주할 수 있다(#462 코드 리뷰, use-class-template-preview.ts와
  // 같은 이유).
  const state: TemplatePreviewState = useMemo(() => {
    if (queryState.status === "loading") return { status: "loading" };
    if (queryState.status === "error") return { status: "error" };
    if (queryState.data === GONE) return { status: "gone" };
    return { status: "ready", template: queryState.data };
  }, [queryState]);

  return { state, reload };
}
