import { describe, expect, it } from "vitest";

import { buildClassroomTabTitle } from "./tab-title";

describe("buildClassroomTabTitle", () => {
  it("문제 제목과 클래스 이름이 모두 있으면 둘을 이어 붙인다", () => {
    expect(
      buildClassroomTabTitle({
        screenName: "문제 제출",
        className: "파이썬 기초반",
        problemTitle: "반복문 연습",
      }),
    ).toBe("문제 제출 · 반복문 연습 · 파이썬 기초반 · Codemit");
  });

  it("클래스 이름만 있으면 화면 이름 뒤에 붙인다", () => {
    expect(
      buildClassroomTabTitle({
        screenName: "클래스 설정",
        className: "파이썬 기초반",
      }),
    ).toBe("클래스 설정 · 파이썬 기초반 · Codemit");
  });

  it("아무 조각도 없으면(불러오기 전 포함) 화면 이름만 쓴다", () => {
    expect(buildClassroomTabTitle({ screenName: "클래스 상세" })).toBe("클래스 상세 · Codemit");
  });

  it("같은 클래스·문제를 여는 화면은 화면 이름으로 갈린다", () => {
    const parts = { className: "처음 쓰는 강사", problemTitle: "두 수 더하기" };
    const edit = buildClassroomTabTitle({ screenName: "문제 편집", ...parts });
    const submissions = buildClassroomTabTitle({ screenName: "제출 현황", ...parts });
    expect(edit).not.toBe(submissions);
    expect(buildClassroomTabTitle({ screenName: "클래스 설정", className: "처음 쓰는 강사" })).not.toBe(
      buildClassroomTabTitle({ screenName: "클래스 상세", className: "처음 쓰는 강사" }),
    );
  });

  it("빈 문자열·공백만 있는 조각은 없는 것으로 본다", () => {
    expect(
      buildClassroomTabTitle({
        screenName: "제출 현황",
        className: "   ",
        problemTitle: "",
      }),
    ).toBe("제출 현황 · Codemit");
  });

  it("문제 제목만 있어도 조립한다", () => {
    expect(
      buildClassroomTabTitle({ screenName: "문제 편집", problemTitle: "반복문 연습" }),
    ).toBe("문제 편집 · 반복문 연습 · Codemit");
  });
});
