import { describe, expect, it } from "vitest";

import { formatRelativeTime } from "./relative-time";

const NOW = Date.parse("2026-10-14T12:00:00Z");
const ago = (ms: number) => new Date(NOW - ms).toISOString();

describe("formatRelativeTime", () => {
  it("값이 없으면 줄표다", () => {
    expect(formatRelativeTime(null, NOW)).toBe("—");
  });

  it("한 시간 안은 방금·분 단위다", () => {
    expect(formatRelativeTime(ago(20_000), NOW)).toBe("방금");
    expect(formatRelativeTime(ago(3 * 60_000), NOW)).toBe("3분 전");
  });

  it("하루 안은 시간, 그 위는 어제·일 단위다", () => {
    expect(formatRelativeTime(ago(2 * 3_600_000), NOW)).toBe("2시간 전");
    expect(formatRelativeTime(ago(30 * 3_600_000), NOW)).toBe("어제");
    expect(formatRelativeTime(ago(3 * 86_400_000), NOW)).toBe("3일 전");
  });

  it("한 달이 넘으면 날짜다", () => {
    expect(formatRelativeTime(ago(40 * 86_400_000), NOW)).toMatch(/2026/);
  });
});
