import { describe, expect, it } from "vitest";

import { attemptAnnouncement } from "./attempt-announcement";

const base = { passed: false, perfect: null, late: null, pending_reason: null } as const;

describe("attemptAnnouncement", () => {
  it("시도가 없으면 비어 있다", () => {
    expect(attemptAnnouncement([])).toBe("");
  });

  it("가장 큰 시도 번호의 상태를 말한다", () => {
    expect(
      attemptAnnouncement([
        { ...base, attempt_number: 1, status: "scored" },
        { ...base, attempt_number: 2, status: "pending" },
      ]),
    ).toBe("시도 2 채점 중");
  });

  it("채점 대기 → 미통과로 바뀌면 문장이 바뀐다, 같은 상태면 같다", () => {
    const waiting = attemptAnnouncement([{ ...base, attempt_number: 1, status: "pending", pending_reason: "no_api_key" }]);
    const done = attemptAnnouncement([{ ...base, attempt_number: 1, status: "scored" }]);
    expect(waiting).toBe("시도 1 채점 대기");
    expect(done).toBe("시도 1 미통과");
    expect(attemptAnnouncement([{ ...base, attempt_number: 1, status: "scored" }])).toBe(done);
  });

  it("통과·완벽·반려", () => {
    expect(attemptAnnouncement([{ ...base, attempt_number: 3, status: "scored", passed: true }])).toBe("시도 3 통과");
    expect(attemptAnnouncement([{ ...base, attempt_number: 3, status: "scored", passed: true, perfect: true }])).toBe("시도 3 완벽");
    expect(attemptAnnouncement([{ ...base, attempt_number: 1, status: "pending", pending_reason: "rejected" }])).toBe("시도 1 반려");
  });
});
