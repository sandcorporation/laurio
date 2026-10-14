import { describe, expect, it } from "vitest";

import type { InstructorSubmissionRow } from "./api";
import {
  latestPerMember,
  participantAttempts,
  participantIdsOf,
  requiredSummary,
  submissionStats,
  syntaxLineReasoning,
} from "./latest-attempts";

function row(over: Partial<InstructorSubmissionRow>): InstructorSubmissionRow {
  return {
    id: 1,
    problem_id: 1,
    member_id: 1,
    member_display_name: "가",
    attempt_number: 1,
    submission_format: "source",
    value: "",
    download_url: null,
    created_at: "2026-10-14T00:00:00Z",
    status: "scored",
    score: null,
    passed: false,
    pending_reason: null,
    contest_entry: null,
    is_current_contest_entry: false,
    ...over,
  } as InstructorSubmissionRow;
}

describe("제출 현황 계산", () => {
  it("사람 집합은 강사 본인과 내보낸 사람을 뺀 참여자다(「제출 현황 N」과 「시도」가 같은 집합)", () => {
    const members = [
      { id: 1, is_instructor: false, expelled: false },
      { id: 2, is_instructor: true, expelled: false },
      { id: 3, is_instructor: false, expelled: true },
    ];
    const ids = participantIdsOf({ members } as never);
    expect([...ids]).toEqual([1]);
    expect(participantAttempts([row({ member_id: 1 }), row({ member_id: 2 }), row({ member_id: 3 })], ids)).toHaveLength(1);
  });

  it("참여자 집합 밖의 시도는 통계에서 빠진다", () => {
    const rows = [row({ id: 1, member_id: 1 }), row({ id: 2, member_id: 9 })];
    expect(participantAttempts(rows, new Set([1])).map((r) => r.id)).toEqual([1]);
    expect(participantAttempts(rows, null)).toHaveLength(2);
  });

  it("통과는 사람 수, 채점 중과 대기는 시도 수로 센다", () => {
    const rows = [
      row({ id: 1, member_id: 1, passed: true }),
      row({ id: 2, member_id: 1, attempt_number: 2, passed: true }),
      row({ id: 3, member_id: 2, status: "pending" }),
      row({ id: 4, member_id: 3, status: "pending", pending_reason: "no_api_key" }),
    ];
    expect(submissionStats(rows, 5)).toEqual({ passed: 1, participants: 5, attempts: 4, scoring: 1, waiting: 1 });
  });

  it("참여자마다 가장 높은 시도 하나, 최근 제출이 위", () => {
    const rows = [
      row({ id: 1, member_id: 1, attempt_number: 1, created_at: "2026-10-14T03:00:00Z" }),
      row({ id: 2, member_id: 1, attempt_number: 2, created_at: "2026-10-14T01:00:00Z" }),
      row({ id: 3, member_id: 2, created_at: "2026-10-14T02:00:00Z" }),
    ];
    expect(latestPerMember(rows).map((r) => r.id)).toEqual([3, 2]);
  });

  it("필수 m/n 과 미충족 항목", () => {
    const items = [
      { id: 10, label: "오류 화면", required: true },
      { id: 11, label: "빈 목록", required: true },
      { id: 12, label: "보너스", required: false },
    ];
    const scored = row({
      score: {
        model_version: "m",
        is_platform_failure: false,
        created_at: "",
        syntax_check: null,
        reasoning: [
          { checklist_item_id: 10, is_met: false, reasoning: "" },
          { checklist_item_id: 11, is_met: true, reasoning: "" },
        ],
      },
    });
    expect(requiredSummary(scored, items, false)).toEqual({ met: 1, total: 2, unmet: ["오류 화면"], syntaxMet: null });
    expect(requiredSummary(row({ status: "pending" }), items, false)).toEqual({ met: null, total: 2, unmet: [], syntaxMet: null });
  });

  // #670 — 분모와 문법 항목은 문제의 지금 `syntax_check_enabled` 로 센다(백엔드 `is_score_passed` 와 같은 기준).
  const items = [{ id: 10, label: "오류 화면", required: true }];
  const verdicts = [{ checklist_item_id: 10, is_met: true, reasoning: "" }];

  it("문법 검사가 켜져 있으면 채점 전에도 분모에 센다", () => {
    expect(requiredSummary(row({ status: "pending" }), items, true)).toEqual({ met: null, total: 2, unmet: [], syntaxMet: null });
  });

  it("문법 결과 없이 만든 자동 미달 점수도 분모가 같고 문법 항목은 미충족이다", () => {
    const autoFail = row({
      score: { model_version: "m",
        is_platform_failure: false, created_at: "", syntax_check: null, reasoning: [] },
    });
    expect(requiredSummary(autoFail, items, true)).toEqual({
      met: 0,
      total: 2,
      unmet: ["오류 화면", "문법 검사"],
      syntaxMet: false,
    });
  });

  it("채점 뒤 문법 검사를 끄면 저장된 문법 오류는 세지 않는다", () => {
    const scored = row({
      passed: true,
      score: {
        model_version: "m",
        is_platform_failure: false,
        created_at: "",
        syntax_check: { is_met: false, reasoning: "", judged_by: "parser", findings: [] },
        reasoning: verdicts,
      },
    });
    expect(requiredSummary(scored, items, false)).toEqual({ met: 1, total: 1, unmet: [], syntaxMet: null });
  });

  it("문법 검사가 켜져 있고 오류가 있으면 「문법 오류」", () => {
    const scored = row({
      score: {
        model_version: "m",
        is_platform_failure: false,
        created_at: "",
        syntax_check: { is_met: false, reasoning: "", judged_by: "parser", findings: [] },
        reasoning: verdicts,
      },
    });
    expect(requiredSummary(scored, items, true)).toEqual({ met: 1, total: 2, unmet: ["문법 오류"], syntaxMet: false });
  });

  it("문법 검사를 통과하면 문법 줄은 충족이다", () => {
    const scored = row({
      score: {
        model_version: "m",
        is_platform_failure: false,
        created_at: "",
        syntax_check: { is_met: true, reasoning: "", judged_by: "parser", findings: [] },
        reasoning: verdicts,
      },
    });
    expect(requiredSummary(scored, items, true)).toEqual({ met: 2, total: 2, unmet: [], syntaxMet: true });
  });
});

describe("syntaxLineReasoning — 문법 줄 밑의 사유(#679)", () => {
  const verdict = { checklist_item_id: 1, is_met: false, reasoning: "첫 항목에 대한 사유" };

  it("일반 점수에 문법 결과가 없으면(채점 뒤 문법 검사를 켰다) 사유를 붙이지 않는다", () => {
    const score = { model_version: "m", is_platform_failure: false, created_at: "", syntax_check: null, reasoning: [verdict] };
    expect(syntaxLineReasoning(score)).toBe("");
  });

  it("플랫폼이 미달로 닫은 점수면 그 점수의 공통 문구를 붙인다", () => {
    const score = { model_version: "x", is_platform_failure: true, created_at: "", syntax_check: null, reasoning: [verdict] };
    expect(syntaxLineReasoning(score)).toBe("첫 항목에 대한 사유");
  });

  it("점수가 없으면 사유도 없다", () => {
    expect(syntaxLineReasoning(null)).toBe("");
  });
});
