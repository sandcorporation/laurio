// spec #474, #478.
import { describe, expect, it } from "vitest";

import { checkDisplayNameForBannedWords } from "./display-name-check";

describe("checkDisplayNameForBannedWords", () => {
  it("사칭 낱말이 있으면 그 종류를 말하는 문구를 돌려준다", () => {
    expect(checkDisplayNameForBannedWords("관리자")).toBe(
      "이름에는 운영진을 뜻하는 말을 쓸 수 없습니다.",
    );
  });

  it("욕설이 있으면 그 종류를 말하는 문구를 돌려준다", () => {
    expect(checkDisplayNameForBannedWords("씨발")).toBe("이름에 욕설을 쓸 수 없습니다.");
  });

  it("정상적인 이름은 통과한다(null)", () => {
    expect(checkDisplayNameForBannedWords("김개발")).toBeNull();
  });

  it("우회 표기는 잡지 않는다", () => {
    expect(checkDisplayNameForBannedWords("관.리.자")).toBeNull();
  });
});
