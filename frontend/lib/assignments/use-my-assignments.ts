"use client";

// 「내 과제」(#207, ADR-0028/0029). `GET /api/assignments/mine`을 BFF 프록시로 친다.
//
// `useMyContests`(lib/sponsorship/use-my-contests.ts)와 짝이지만 `usePagedList`가
// 아니라 `useBackendQuery`를 쓴다 — 백엔드 `list_my_assignments`가 커서 페이지네이션
// 없이 `list[AssignmentOut]`을 그대로 돌려준다(Sponsor 한 명이 여는 과제 수는 공모전과
// 달리 무한정 쌓일 유인이 크지 않다고 판단했다, `contests.assignment_api`). 값이 하나
// 늘면 이 계약이 갈리므로, 나중에 페이지네이션이 필요해지면 백엔드·프론트를 같은
// 커밋에서 함께 고친다.
import { useBackendQuery } from "@laurio/bff-client";
import type { components } from "@laurio/bff-client/schema";

import { bffClient } from "@/lib/bff/client";

export type AssignmentRow = components["schemas"]["AssignmentOut"];

/** `Contest.Status` 값의 한국어 표기 — 목록(`console/assignments/page.tsx`)과
 * 상세(`console/assignments/[assignmentId]/page.tsx`)가 같은 표를 쓴다. 두 곳에
 * 따로 두면 값이 하나 늘었을 때 한쪽만 고쳐 화면마다 다른 문구가 뜰 수 있다. */
export const ASSIGNMENT_STATUS_LABELS: Record<string, string> = {
  draft: "초안",
  assignment_open: "진행중",
  assignment_closed: "마감",
};

export type MyAssignmentsState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; rows: AssignmentRow[] };

export function useMyAssignments(): MyAssignmentsState & { reload: () => void } {
  const { state, reload } = useBackendQuery<AssignmentRow[]>(
    bffClient,
    "/api/backend/assignments/mine",
  );

  if (state.status === "loading") return { status: "loading", reload };
  if (state.status === "error") return { status: "error", reload };
  return { status: "ready", rows: state.data, reload };
}
