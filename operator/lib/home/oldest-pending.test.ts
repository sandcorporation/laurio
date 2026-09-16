import { describe, expect, it } from "vitest";

import { oldestPendingDays } from "./oldest-pending";

describe("오늘 밀린 지 며칠인가 (#427)", () => {
  it("빈 목록은 「모른다」가 아니라 「밀린 것이 없다」다", () => {
    expect(oldestPendingDays([])).toBeNull();
  });

  it("가장 오래된 접수를 기준으로 날짜 수를 센다", () => {
    const now = new Date("2026-09-16T00:00:00Z");
    const createdAt = [
      "2026-09-15T00:00:00Z",
      "2026-09-13T00:00:00Z", // 가장 오래됨 — 3일 전
      "2026-09-16T00:00:00Z",
    ];
    expect(oldestPendingDays(createdAt, now)).toBe(3);
  });

  it("오늘 접수된 것만 있으면 0일이다 — 음수로 새지 않는다", () => {
    const now = new Date("2026-09-16T12:00:00Z");
    expect(oldestPendingDays(["2026-09-16T23:00:00Z"], now)).toBe(0);
  });
});
