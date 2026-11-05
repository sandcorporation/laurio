import { describe, expect, it } from "vitest";

import { effectiveNotice, isInForce, koreanDate } from "./effective-notice";

const EFFECTIVE = "2026-11-12";

describe("effectiveNotice", () => {
  it("시행일 전에는 개정 예정을 붙인다", () => {
    expect(effectiveNotice(EFFECTIVE, new Date("2026-11-05T03:00:00Z"))).toBe(
      "개정 예정 · 시행일 2026년 11월 12일",
    );
  });

  it("시행일 전날 KST 자정 직전까지 개정 예정이다", () => {
    // 2026-11-11T14:59:59Z = KST 11월 11일 23:59:59
    expect(isInForce(EFFECTIVE, new Date("2026-11-11T14:59:59Z"))).toBe(false);
  });

  it("시행일 당일(KST 00:00)부터는 표시가 없다", () => {
    // 2026-11-11T15:00:00Z = KST 11월 12일 00:00
    const now = new Date("2026-11-11T15:00:00Z");
    expect(isInForce(EFFECTIVE, now)).toBe(true);
    expect(effectiveNotice(EFFECTIVE, now)).toBe("시행일 2026년 11월 12일");
  });

  it("시행일 이후에도 표시가 없다", () => {
    expect(effectiveNotice(EFFECTIVE, new Date("2027-01-01T00:00:00Z"))).toBe(
      "시행일 2026년 11월 12일",
    );
  });

  it("날짜를 한국어로 적는다", () => {
    expect(koreanDate("2026-10-03")).toBe("2026년 10월 3일");
  });
});
