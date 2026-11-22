"use client";

// 클래스 「제출」 화면(#1317)의 상태 — 「최근 제출」과 같은 줄을 최신순으로 쪽을 넘기며 읽는다. 줄마다 「다시 채점」을
// 걸 수 있나(`correctable`)는 백엔드 `score_corrections.correctable` 이 정한다.
import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";
import type { RecentAttemptRow } from "@/lib/classes/use-recent-attempts";

export type ClassAttemptRow = RecentAttemptRow & { correctable: boolean };

export type ClassAttemptPage = { rows: ClassAttemptRow[]; page: number; has_next: boolean };

export function classAttemptsPath(classId: number, page: number): string {
  return `/api/backend/classroom/classes/${classId}/attempts?page=${page}`;
}

export function useClassAttempts(classId: number, page: number) {
  return useBackendQuery<ClassAttemptPage>(bffClient, classAttemptsPath(classId, page));
}

type CorrectionRequestBody = {
  corrections: { id: number; submission_id: number; status: string }[];
  skipped: { submission_id: number; reason: string }[];
};

/** 「다시 채점」 — 시도 하나에 정정을 건다. 사유는 보내지 않는다(백엔드가 「채점 실패 다시 채점」으로 둔다). */
export function requestRegrade(classId: number, submissionId: number) {
  return bffClient.post<CorrectionRequestBody>(`/api/backend/classroom/classes/${classId}/score-corrections`, {
    submission_ids: [submissionId],
  });
}
