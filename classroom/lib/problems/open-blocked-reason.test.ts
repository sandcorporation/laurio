import { describe, expect, it } from "vitest";

import { openBlockedReason } from "./open-blocked-reason";

describe("openBlockedReason", () => {
  it("필수 항목만 없어 꺼졌으면 이유를 준다", () => {
    expect(openBlockedReason({ createDisabled: false, hasRequiredItem: false })).toBe(
      "필수 항목이 없어 아직 열 수 없습니다.",
    );
  });

  it("필수 항목이 있으면 이유가 없다", () => {
    expect(openBlockedReason({ createDisabled: false, hasRequiredItem: true })).toBeNull();
  });

  it("다른 까닭으로 이미 꺼졌으면 필수 항목 이유를 대지 않는다", () => {
    expect(openBlockedReason({ createDisabled: true, hasRequiredItem: false })).toBeNull();
  });
});
