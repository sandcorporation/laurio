// spec #474, #479.
import { describe, expect, it } from "vitest";

import { checkPublicTextForBannedWords } from "./public-text-check";

describe("checkPublicTextForBannedWords", () => {
  it("욕설이 있으면 그 필드 이름을 담은 문구를 돌려준다", () => {
    expect(checkPublicTextForBannedWords("씨발", "제목")).toBe("제목에 욕설을 쓸 수 없습니다.");
  });

  it("사칭 낱말은 걸지 않는다 — 「관리자 페이지 만들기」는 정당한 문제 제목이다", () => {
    expect(checkPublicTextForBannedWords("관리자 페이지 만들기", "제목")).toBeNull();
  });

  it("정상적인 글은 통과한다(null)", () => {
    expect(checkPublicTextForBannedWords("1주차 — Todo API", "제목")).toBeNull();
  });
});
