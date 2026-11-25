import { describe, expect, it } from "vitest";

import { requiredSummary } from "../submissions/latest-attempts";

import { problemRequiredCount } from "./required-count";

const items = [
  { id: 1, label: "a", required: true },
  { id: 2, label: "b", required: true },
  { id: 3, label: "c", required: false },
];

describe("problemRequiredCount", () => {
  it("문법 검사가 켜져 있으면 자동 항목을 센다 — 참여자 화면과 같은 수", () => {
    const problem = { checklist_items: items, syntax_check_enabled: true };
    expect(problemRequiredCount(problem)).toBe(3);
    expect(problemRequiredCount(problem)).toBe(
      requiredSummary({ status: "pending", score: null }, items, true).total,
    );
  });

  it("문법 검사를 끄면 자동 항목을 세지 않는다", () => {
    expect(problemRequiredCount({ checklist_items: items, syntax_check_enabled: false })).toBe(2);
  });
});
