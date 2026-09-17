import { describe, expect, it } from "vitest";

import { classNamesPatch } from "./name-patch";

const saved = { name: "웹 스터디", instructorDisplayName: "김강사" };

describe("classNamesPatch", () => {
  it("바뀐 것이 없으면 보낼 것이 없다", () => {
    expect(classNamesPatch(saved, { name: "웹 스터디", instructorDisplayName: "김강사" })).toBeNull();
  });

  it("앞뒤 공백만 다르면 바뀐 것으로 보지 않는다", () => {
    expect(classNamesPatch(saved, { name: "  웹 스터디 ", instructorDisplayName: "김강사 " })).toBeNull();
  });

  it("클래스 이름만 바뀌면 그것만 싣는다", () => {
    expect(classNamesPatch(saved, { name: " 웹 스터디 2기 ", instructorDisplayName: "김강사" })).toEqual({
      name: "웹 스터디 2기",
    });
  });

  it("강사 이름만 바뀌면 그것만 싣는다", () => {
    expect(classNamesPatch(saved, { name: "웹 스터디", instructorDisplayName: "박강사" })).toEqual({
      instructor_display_name: "박강사",
    });
  });

  it("둘 다 바뀌면 둘 다 싣는다", () => {
    expect(classNamesPatch(saved, { name: "새 반", instructorDisplayName: "박강사" })).toEqual({
      name: "새 반",
      instructor_display_name: "박강사",
    });
  });

  it("어느 한쪽이라도 비어 있으면 보내지 않는다", () => {
    expect(classNamesPatch(saved, { name: "   ", instructorDisplayName: "박강사" })).toBeNull();
    expect(classNamesPatch(saved, { name: "새 반", instructorDisplayName: "" })).toBeNull();
  });
});
