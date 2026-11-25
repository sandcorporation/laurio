import { describe, expect, it } from "vitest";

import { INPUT_LIMITS, charCountText } from "./limits";

describe("INPUT_LIMITS", () => {
  it("서버 스키마의 상한과 같다", () => {
    expect(INPUT_LIMITS).toEqual({
      newClassName: 200,
      newClassInstructorName: 100,
      joinDisplayName: 100,
      newProblemTitle: 200,
      editProblemTitle: 200,
      newChecklistLabel: 200,
      editChecklistLabel: 200,
      gradingGuidelineText: 500,
    });
  });
});

describe("charCountText — CharCount 가 그리는 글자", () => {
  it.each([
    [179, 200, null],
    [180, 200, "180/200"],
    [200, 200, "200/200"],
    [89, 100, null],
    [90, 100, "90/100"],
    [449, 500, null],
    [450, 500, "450/500"],
  ])("%i자 / 상한 %i", (length, limit, expected) => {
    expect(charCountText(length, limit)).toBe(expected);
  });
});
