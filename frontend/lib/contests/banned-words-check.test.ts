// spec #474, #479.
import { describe, expect, it } from "vitest";

import { checkPublicTextForBannedWords } from "./banned-words-check";

describe("checkPublicTextForBannedWords", () => {
  it("욕설이 있으면 그 필드 이름을 담은 문구를 돌려준다", () => {
    expect(checkPublicTextForBannedWords("씨발", "제목")).toBe("제목에 욕설을 쓸 수 없습니다.");
  });

  it("사칭 낱말은 걸지 않는다 — 「운영자 대시보드」는 정당한 공모전 제목이다", () => {
    expect(checkPublicTextForBannedWords("운영자 대시보드", "제목")).toBeNull();
  });

  it("「관리자 페이지 만들기」도 통과한다", () => {
    expect(checkPublicTextForBannedWords("관리자 페이지 만들기", "제목")).toBeNull();
  });

  it("정상적인 글은 통과한다(null)", () => {
    expect(checkPublicTextForBannedWords("프론트엔드 스터디 모집", "제목")).toBeNull();
  });
});
