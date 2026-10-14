// 제출 현황(#638, 시안 v2)의 계산 — 화면이 받는 시도 목록에서 통계 바·참여자별 최신 시도·필수 m/n 을 센다.
// 사람 집합은 참여자 격자에서 온다(강사·내보낸 사람 제외) — 클래스 상세의 달성률과 같은 집합이다.
import type { RosterGrid } from "@/lib/roster-grid/api";

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

/** 제출 현황의 사람 집합 — 격자의 참여자에서 강사 본인과 내보낸 사람을 뺀다. */
export function participantIdsOf(grid: Pick<RosterGrid, "members">): Set<number> {
  return new Set(grid.members.filter((m) => !m.is_instructor && !m.expelled).map((m) => m.id));
}

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
  /**
   * 문법 검사 줄의 판정(#674) — 문법 검사가 꺼져 있거나 채점 전이면 null. 문법 결과 없이 만든
   * 자동 미달 점수(실패 상한)는 거짓이다 — 카드의 문법 줄이 머리 배지·미충족 목록과 같은 판정을 그린다.
   */
  syntaxMet: boolean | null;
};

/**
 * 「필수 m/n」 — 필수 체크리스트 항목과 문법 검사 기본 항목을 센다.
 *
 * 문법 항목은 **문제의 지금 `syntax_check_enabled`** 로 센다(#670) — 통과 배지를 정하는
 * 백엔드 `Problem.is_score_passed` 와 같은 기준이다. 저장된 결과(`score.syntax_check`)의
 * 유무로 세면 문법 결과 없이 만든 자동 미달 점수(실패 상한)만 분모가 하나 작고, 채점 뒤
 * 문법 검사를 끄면 「통과」와 「문법 오류」가 함께 보인다. 진행 막대의 분모도 이 값을 쓴다.
 */
export function requiredSummary(
  row: Pick<InstructorSubmissionRow, "status" | "score">,
  items: ReadonlyArray<{ id: number; label: string; required: boolean }>,
  syntaxCheckEnabled: boolean,
): RequiredSummary {
  const required = items.filter((item) => item.required);
  const total = required.length + (syntaxCheckEnabled ? 1 : 0);
  if (row.status !== "scored" || !row.score) return { met: null, total, unmet: [], syntaxMet: null };
  const verdicts = new Map(row.score.reasoning.map((v) => [v.checklist_item_id, v.is_met]));
  const unmet = required.filter((item) => verdicts.get(item.id) !== true).map((item) => item.label);
  let syntaxMet: boolean | null = null;
  if (syntaxCheckEnabled) {
    const syntax = row.score.syntax_check;
    syntaxMet = syntax ? syntax.is_met : false;
    if (!syntax) unmet.push("문법 검사");
    else if (!syntax.is_met) unmet.push("문법 오류");
  }
  return { met: total - unmet.length, total, unmet, syntaxMet };
}
