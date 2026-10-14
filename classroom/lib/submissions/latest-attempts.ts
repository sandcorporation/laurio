// 제출 현황(#638, 시안 v2)의 계산 — 화면이 받는 시도 목록에서 통계 바·참여자별 최신 시도·필수 m/n 을 센다.
// 사람 집합은 참여자 격자에서 온다(강사·내보낸 사람 제외) — 클래스 상세의 달성률과 같은 집합이다.
import type { InstructorSubmissionRow } from "./api";

export type SubmissionStats = {
  /** 한 번이라도 통과한 참여자 수. */
  passed: number;
  /** 분모(참여자 수). 격자를 아직 못 받았으면 null. */
  participants: number | null;
  attempts: number;
  scoring: number;
  waiting: number;
};

/** 참여자 집합이 있으면 그 밖의 시도(강사 본인·내보낸 사람)는 뺀다. */
export function participantAttempts(
  rows: InstructorSubmissionRow[],
  memberIds: ReadonlySet<number> | null,
): InstructorSubmissionRow[] {
  return memberIds === null ? rows : rows.filter((row) => memberIds.has(row.member_id));
}

export function submissionStats(
  rows: InstructorSubmissionRow[],
  participants: number | null,
): SubmissionStats {
  const passedMembers = new Set<number>();
  let scoring = 0;
  let waiting = 0;
  for (const row of rows) {
    if (row.passed) passedMembers.add(row.member_id);
    if (row.status === "pending") {
      if (row.pending_reason) waiting += 1;
      else scoring += 1;
    }
  }
  return { passed: passedMembers.size, participants, attempts: rows.length, scoring, waiting };
}

/** 참여자마다 가장 높은 시도 번호 한 줄 — 가장 최근에 낸 사람이 위. */
export function latestPerMember(rows: InstructorSubmissionRow[]): InstructorSubmissionRow[] {
  const latest = new Map<number, InstructorSubmissionRow>();
  for (const row of rows) {
    const current = latest.get(row.member_id);
    if (current === undefined || row.attempt_number > current.attempt_number) {
      latest.set(row.member_id, row);
    }
  }
  return [...latest.values()].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
}

export type RequiredSummary = {
  /** 충족한 필수 항목 수 — 채점 전이면 null. */
  met: number | null;
  total: number;
  /** 미충족 필수 항목의 이름. */
  unmet: string[];
};

/** 「필수 m/n」 — 필수 체크리스트 항목과(결과에 실렸다면) 문법 검사 기본 항목을 센다. */
export function requiredSummary(
  row: Pick<InstructorSubmissionRow, "status" | "score">,
  items: ReadonlyArray<{ id: number; label: string; required: boolean }>,
): RequiredSummary {
  const required = items.filter((item) => item.required);
  const syntaxTotal = row.score?.syntax_check ? 1 : 0;
  const total = required.length + (row.status === "scored" ? syntaxTotal : 0);
  if (row.status !== "scored" || !row.score) return { met: null, total, unmet: [] };
  const verdicts = new Map(row.score.reasoning.map((v) => [v.checklist_item_id, v.is_met]));
  const unmet = required.filter((item) => verdicts.get(item.id) !== true).map((item) => item.label);
  if (row.score.syntax_check && !row.score.syntax_check.is_met) unmet.push("문법 오류");
  return { met: total - unmet.length, total, unmet };
}
