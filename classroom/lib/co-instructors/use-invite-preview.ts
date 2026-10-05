"use client";

// 공동 강사 초대 미리보기 상태 (#561) — 가입 링크의 `useJoinPreview`와 같은 모양이다.
// 없는 토큰은 백엔드가 이유를 담은 404를 준다 — 그 문구를 그대로 보여준다. 쓰였거나
// 만료·취소된 초대는 404가 아니라 `status`로 온다(받은 사람이 새 링크를 부탁할 수 있게).
import { useMemo } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { CoInstructorInvitePreview } from "./api";

export type InvitePreviewState =
  | { status: "loading" }
  | { status: "dead"; reason: string }
  | { status: "error" }
  | { status: "ready"; preview: CoInstructorInvitePreview };

type Dead = { kind: "invite-preview-dead"; reason: string };

export function useInvitePreview(token: string): InvitePreviewState {
  const { state: queryState } = useBackendQuery<CoInstructorInvitePreview | Dead>(
    bffClient,
    `/api/backend/classroom/co-instructor-invites/${token}`,
    {
      onFailure: (failure) =>
        failure.status === 404 ? { kind: "invite-preview-dead", reason: failure.detail } : undefined,
    },
  );

  return useMemo<InvitePreviewState>(() => {
    if (queryState.status === "loading") return { status: "loading" };
    if (queryState.status === "error") return { status: "error" };
    if ("kind" in queryState.data) return { status: "dead", reason: queryState.data.reason };
    return { status: "ready", preview: queryState.data };
  }, [queryState]);
}
