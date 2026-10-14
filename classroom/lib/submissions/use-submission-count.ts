"use client";

// 문제 편집 머리의 「제출 현황 N」 (#637) — 이 문제에 들어온 시도의 수만 읽는다. 목록 자체는
// 제출 현황 화면이 그린다. 실시간 갱신은 걸지 않는다(이 화면의 숫자는 눈금일 뿐이다).
import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { InstructorSubmissionRow } from "./api";

/** 시도 수 — 아직 못 읽었거나 읽지 못하면 null(머리는 숫자 없이 「제출 현황」만 보인다). */
export function useSubmissionCount(classId: number, problemId: number): number | null {
  const { state } = useBackendQuery<InstructorSubmissionRow[]>(
    bffClient,
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/submissions`,
  );
  return state.status === "ready" ? state.data.length : null;
}
