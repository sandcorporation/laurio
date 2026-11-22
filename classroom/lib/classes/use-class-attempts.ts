"use client";

// 클래스 「제출」 화면(#1317)의 상태 — 「최근 제출」과 같은 줄을 최신순으로 쪽을 넘기며 읽는다. 줄마다 「다시 채점」을
// 걸 수 있나(`correctable`)는 백엔드 `score_corrections.correctable` 이 정한다.
import { useCallback } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";
import { ATTEMPT_SCORED, type StreamEvent } from "@/lib/events/types";
import { useRealtimeRefresh } from "@/lib/events/use-realtime-refresh";
import type { ClassroomScore } from "@/lib/submissions/api";
import type { RecentAttemptRow } from "@/lib/classes/use-recent-attempts";

export type ClassAttemptRow = RecentAttemptRow & { correctable: boolean };

export type ClassAttemptPage = { rows: ClassAttemptRow[]; page: number; has_next: boolean };

export function classAttemptsPath(classId: number, page: number): string {
  return `/api/backend/classroom/classes/${classId}/attempts?page=${page}`;
}

/** 줄을 펼쳤을 때(#1334) 그 시도 하나의 현재 판정 — 채점 전이면 `score` 가 null. */
export type ClassAttemptVerdicts = {
  score: ClassroomScore | null;
  checklist_items: { id: number; label: string }[];
};

export function classAttemptVerdictsPath(classId: number, submissionId: number): string {
  return `/api/backend/classroom/classes/${classId}/attempts/${submissionId}/verdicts`;
}

const FALLBACK_POLL_MS = 30_000;

/** 채점·다시 채점이 끝나면(attempt-scored) 다시 읽는다 — 「최근 제출」 카드와 같은 신호다. */
export function useClassAttempts(classId: number, page: number) {
  const { state, reload: refetch } = useBackendQuery<ClassAttemptPage>(bffClient, classAttemptsPath(classId, page));
  const reload = useCallback(() => {
    refetch();
  }, [refetch]);
  const matches = useCallback(
    (event: StreamEvent) => event.kind === ATTEMPT_SCORED && event.payload.class_id === classId,
    [classId],
  );
  useRealtimeRefresh({ matches, waiting: true, fallbackPollMs: FALLBACK_POLL_MS, reload });
  return { state, reload };
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
