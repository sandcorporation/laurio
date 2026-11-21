import { describe, expect, it } from "vitest";

import { certificateStatus, defaultAwardDate, type CertificateOut } from "./types";

const base = { cancelled_at: null, replaced_by_id: null } as CertificateOut;

describe("certificateStatus", () => {
  it("취소되지 않았으면 유효", () => {
    expect(certificateStatus(base)).toBe("valid");
  });
  it("취소만 했으면 취소됨", () => {
    expect(certificateStatus({ ...base, cancelled_at: "2026-11-21T00:00:00Z" })).toBe("cancelled");
  });
  it("취소하고 다시 발급했으면 다시 발급됨", () => {
    expect(certificateStatus({ ...base, cancelled_at: "2026-11-21T00:00:00Z", replaced_by_id: 9 })).toBe("replaced");
  });
});

describe("defaultAwardDate", () => {
  it("오늘이 범위 안이면 오늘", () => {
    expect(defaultAwardDate("2026-11-01", "2026-12-21", "2026-11-21")).toBe("2026-11-21");
  });
  it("범위 밖이면 가장 가까운 끝", () => {
    expect(defaultAwardDate("2026-11-22", "2026-12-21", "2026-11-21")).toBe("2026-11-22");
    expect(defaultAwardDate("2026-10-01", "2026-10-31", "2026-11-21")).toBe("2026-10-31");
  });
});
