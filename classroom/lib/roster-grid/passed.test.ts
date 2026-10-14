import { describe, expect, it } from "vitest";

import { openPassedSummary } from "./passed";

const problems = [
  { id: 1, status: "open" },
  { id: 2, status: "draft" },
  { id: 3, status: "hidden" },
  { id: 4, status: "open" },
];

describe("openPassedSummary", () => {
  it("n·N 모두 열린 문제만 센다 — 초안·숨김에서 통과한 것은 빠진다", () => {
    const member = {
      cells: [
        { problem_id: 1, status: "passed" as const },
        { problem_id: 2, status: "passed" as const },
        { problem_id: 3, status: "passed" as const },
        { problem_id: 4, status: "attempted_not_passed" as const },
      ],
    };
    expect(openPassedSummary(problems, member)).toBe("1/2");
  });

  it("열린 문제가 없으면 「—」", () => {
    expect(openPassedSummary([{ id: 2, status: "draft" }], { cells: [] })).toBe("—");
  });
});
