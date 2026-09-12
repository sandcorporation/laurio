import { describe, expect, it } from "vitest";

import { shouldShowMissingScoringKeyBanner } from "./missing-scoring-key-banner";

describe("shouldShowMissingScoringKeyBanner", () => {
  it("진행중 · 키 없음 — 뜬다", () => {
    expect(shouldShowMissingScoringKeyBanner({ archived: false, has_openai_key: false })).toBe(true);
  });

  it("진행중 · 키 있음 — 안 뜬다", () => {
    expect(shouldShowMissingScoringKeyBanner({ archived: false, has_openai_key: true })).toBe(false);
  });

  it("보관됨 · 키 없음 — 새 제출을 안 받으니 안 뜬다(#352)", () => {
    expect(shouldShowMissingScoringKeyBanner({ archived: true, has_openai_key: false })).toBe(false);
  });

  it("보관됨 · 키 있음 — 안 뜬다", () => {
    expect(shouldShowMissingScoringKeyBanner({ archived: true, has_openai_key: true })).toBe(false);
  });
});
