// spec #474, #476. 아래 케이스는 backend/tests/test_classroom_banned_words.py 와
// 같은 문자열을 쓴다 — "판정 결과가 백엔드와 같다"(#476 AC)를 같은 입력·같은
// 기대값으로 나란히 고정한다.
import { describe, expect, it } from "vitest";

import { findBannedWordViolation } from "./judge";

describe("findBannedWordViolation", () => {
  it("사칭 낱말이 있으면 impersonation을 돌려준다", () => {
    expect(findBannedWordViolation("관리자", { checkImpersonation: true })).toBe(
      "impersonation",
    );
  });

  it("영문 사칭 낱말은 대소문자를 가리지 않는다", () => {
    expect(findBannedWordViolation("Class ADMIN", { checkImpersonation: true })).toBe(
      "impersonation",
    );
  });

  it("욕설이 있으면 profanity를 돌려준다", () => {
    expect(findBannedWordViolation("씨발놈", { checkImpersonation: true })).toBe("profanity");
  });

  it("정상적인 값은 통과한다(null)", () => {
    expect(findBannedWordViolation("김개발", { checkImpersonation: true })).toBeNull();
  });

  it("우회 표기는 일부러 잡지 않는다 — 결정이므로 고정한다", () => {
    expect(findBannedWordViolation("관.리.자", { checkImpersonation: true })).toBeNull();
  });

  it("checkImpersonation이 거짓이면 사칭 목록은 보지 않는다 — 제목·본문이 이렇게 부른다", () => {
    // 「관리자 페이지 만들기」 같은 정당한 제목이 막히면 안 된다(spec #474).
    expect(findBannedWordViolation("관리자 페이지 만들기", { checkImpersonation: false })).toBeNull();
  });

  it("checkImpersonation이 거짓이어도 욕설은 여전히 걸린다", () => {
    expect(findBannedWordViolation("씨발 페이지", { checkImpersonation: false })).toBe(
      "profanity",
    );
  });

  it("빈 문자열은 통과한다", () => {
    expect(findBannedWordViolation("", { checkImpersonation: true })).toBeNull();
  });
});
