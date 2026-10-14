"use client";

// 문제 편집 머리의 「제출 현황 N」 (#637) — 이 문제에 들어온 시도의 수만 읽는다. 목록 자체는
// 제출 현황 화면이 그린다. 실시간 갱신은 걸지 않는다(이 화면의 숫자는 눈금일 뿐이다).
//
// 제출 현황의 「시도」와 같은 집합을 센다(#670) — 강사 본인과 내보낸 사람의 시도는 뺀다. 시도 수만
// 주는 백엔드 값이 없어 시도 목록과 격자를 함께 받아 거른다(숫자 하나에 판정까지 실린 목록 전체를
// 받는 비용은 남는다 — 백엔드 count 는 후속).
import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";
import type { RosterGrid } from "@/lib/roster-grid/api";

import type { InstructorSubmissionRow } from "./api";
import { participantAttempts, participantIdsOf } from "./latest-attempts";

/** 참여자의 시도 수 — 아직 못 읽었거나 읽지 못하면 null(머리는 숫자 없이 「제출 현황」만 보인다). */
export function useSubmissionCount(classId: number, problemId: number): number | null {
  const { state } = useBackendQuery<InstructorSubmissionRow[]>(
    bffClient,
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/submissions`,
  );
  const { state: gridState } = useBackendQuery<RosterGrid>(
    bffClient,
    `/api/backend/classroom/classes/${classId}/roster-grid`,
  );
  if (state.status !== "ready" || gridState.status !== "ready") return null;
  return participantAttempts(state.data, participantIdsOf(gridState.data)).length;
}
