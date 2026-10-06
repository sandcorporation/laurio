import { describe, expect, it } from "vitest";

import {
  shouldShowExhaustedCreditBanner,
  shouldShowMissingScoringKeyBanner,
  shouldShowRejectedScoringKeyBanner,
} from "./missing-scoring-key-banner";

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

describe("shouldShowRejectedScoringKeyBanner", () => {
  it("진행중 · 키 거부됨 — 뜬다(#355)", () => {
    expect(
      shouldShowRejectedScoringKeyBanner({
        archived: false,
        has_openai_key: true,
        openai_key_status: "rejected",
      }),
    ).toBe(true);
  });

  it("진행중 · 키 확인함 — 안 뜬다", () => {
    expect(
      shouldShowRejectedScoringKeyBanner({
        archived: false,
        has_openai_key: true,
        openai_key_status: "verified",
      }),
    ).toBe(false);
  });

  it("진행중 · 키 없음 — 거부 배너는 안 뜬다(「없음」 배너의 몫이다)", () => {
    expect(
      shouldShowRejectedScoringKeyBanner({
        archived: false,
        has_openai_key: false,
        openai_key_status: null,
      }),
    ).toBe(false);
  });

  it("보관됨 · 키 거부됨 — 새 제출을 안 받으니 안 뜬다", () => {
    expect(
      shouldShowRejectedScoringKeyBanner({
        archived: true,
        has_openai_key: true,
        openai_key_status: "rejected",
      }),
    ).toBe(false);
  });
});

describe("shouldShowExhaustedCreditBanner", () => {
  const base = {
    archived: false,
    has_openai_key: true,
    openai_key_status: "verified" as const,
    scoring_quota_exhausted: true,
  };

  it("진행중 · 크레딧 소진 — 뜬다(#586)", () => {
    expect(shouldShowExhaustedCreditBanner(base)).toBe(true);
  });

  it("진행중 · 크레딧 남음 — 안 뜬다", () => {
    expect(shouldShowExhaustedCreditBanner({ ...base, scoring_quota_exhausted: false })).toBe(false);
  });

  it("키가 거부됐으면 거부 배너의 몫이다", () => {
    expect(shouldShowExhaustedCreditBanner({ ...base, openai_key_status: "rejected" })).toBe(false);
  });

  it("보관됨 — 새 제출을 안 받으니 안 뜬다", () => {
    expect(shouldShowExhaustedCreditBanner({ ...base, archived: true })).toBe(false);
  });
});
