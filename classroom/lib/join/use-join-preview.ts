"use client";

// 가입 링크 미리보기 상태 (#280). 죽은 링크(재발급으로 죽었거나 애초에 없는
// 코드)는 백엔드가 이유를 담은 404를 준다 — 그 문구를 그대로 보여준다(둘을
// 구별해 보여줄 필요가 없다는 것도 백엔드가 이미 정한 결정이다,
// backend/classroom/api.py의 `_get_class_by_join_code_or_404`). 공유
// 클라이언트 위에 선다(#462).
import { useMemo } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { JoinPreview } from "./api";

export type JoinPreviewState =
  | { status: "loading" }
  | { status: "dead"; reason: string }
  | { status: "error" }
  | { status: "ready"; preview: JoinPreview };

type Dead = { kind: "join-preview-dead"; reason: string };

export function useJoinPreview(code: string): JoinPreviewState {
  const { state: queryState } = useBackendQuery<JoinPreview | Dead>(
    bffClient,
    `/api/backend/classroom/join/${code}`,
    {
      onFailure: (failure) =>
        failure.status === 404 ? { kind: "join-preview-dead", reason: failure.detail } : undefined,
    },
  );

  // useMemo 없이 매 렌더 새 객체를 만들면 그 객체를 effect 의존성으로 쓰는
  // 호출부(이미 참여한 사람을 문제 목록으로 돌려보내는 effect 등)가 폭주할
  // 수 있다(#462 코드 리뷰).
  return useMemo<JoinPreviewState>(() => {
    if (queryState.status === "loading") return { status: "loading" };
    if (queryState.status === "error") return { status: "error" };
    if ("kind" in queryState.data) return { status: "dead", reason: queryState.data.reason };
    return { status: "ready", preview: queryState.data };
  }, [queryState]);
}
