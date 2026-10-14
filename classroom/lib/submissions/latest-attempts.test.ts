import { describe, expect, it } from "vitest";

import type { InstructorSubmissionRow } from "./api";
import { latestPerMember, participantAttempts, requiredSummary, submissionStats } from "./latest-attempts";

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
        created_at: "",
        syntax_check: null,
        reasoning: [
          { checklist_item_id: 10, is_met: false, reasoning: "" },
          { checklist_item_id: 11, is_met: true, reasoning: "" },
        ],
      },
    });
    expect(requiredSummary(scored, items)).toEqual({ met: 1, total: 2, unmet: ["오류 화면"] });
    expect(requiredSummary(row({ status: "pending" }), items)).toEqual({ met: null, total: 2, unmet: [] });
  });
});
