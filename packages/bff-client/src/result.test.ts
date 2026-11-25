import { describe, expect, it } from "vitest";

import { FALLBACK_DETAIL, normalizeDetail } from "./result";

const tooLong = {
  type: "string_too_long",
  loc: ["body", "payload", "name"],
  msg: "String should have at most 200 characters",
  ctx: { max_length: 200 },
};

describe("normalizeDetail", () => {
  it.each([
    ["상한 초과, 라벨 있음", [tooLong], { name: "클래스 이름" }, "클래스 이름: 200자까지 쓸 수 있습니다."],
    ["상한 초과, 라벨 없음", [tooLong], undefined, "200자까지 쓸 수 있습니다."],
    [
      "빈 값",
      [{ type: "string_too_short", loc: ["body", "payload", "title"], msg: "String should have at least 1 character", ctx: { min_length: 1 } }],
      { title: "제목" },
      "제목: 비워 둘 수 없습니다.",
    ],
    [
      "빠진 값",
      [{ type: "missing", loc: ["body", "payload", "instructor_display_name"], msg: "Field required" }],
      undefined,
      "빠진 값이 있습니다.",
    ],
    [
      "한국어 검증기 문구",
      [{ type: "value_error", loc: ["body", "payload"], msg: "Value error, 저장소 주소가 올바르지 않습니다." }],
      undefined,
      "저장소 주소가 올바르지 않습니다.",
    ],
    [
      "영어 검증기 문구",
      [{ type: "value_error", loc: ["body", "payload", "url"], msg: "Value error, invalid url" }],
      undefined,
      "입력값을 확인해 주세요.",
    ],
    [
      "표에 없는 type",
      [{ type: "int_parsing", loc: ["body", "payload", "points"], msg: "Input should be a valid integer" }],
      { points: "점수" },
      "점수: 입력값을 확인해 주세요.",
    ],
    ["문자열 detail", "클래스를 찾을 수 없습니다.", undefined, "클래스를 찾을 수 없습니다."],
  ])("%s", (_name, detail, fieldLabels, expected) => {
    expect(normalizeDetail(detail, FALLBACK_DETAIL, fieldLabels)).toBe(expected);
  });

  it("type 이 없어도 영어 msg 와 필드명은 나가지 않는다", () => {
    expect(normalizeDetail([{ loc: ["body", "payload", "title"], msg: "Field required" }])).toBe("입력값을 확인해 주세요.");
  });

  it("여러 항목은 공백으로 잇는다", () => {
    expect(normalizeDetail([tooLong, { type: "missing", loc: ["body", "payload", "x"], msg: "Field required" }])).toBe(
      "200자까지 쓸 수 있습니다. 빠진 값이 있습니다.",
    );
  });

  it("객체의 상속 속성은 라벨이 아니다", () => {
    expect(normalizeDetail([{ ...tooLong, loc: ["body", "constructor"] }], FALLBACK_DETAIL, {})).toBe(
      "200자까지 쓸 수 있습니다.",
    );
  });

  it("알 수 없는 모양은 폴백이다", () => {
    expect(normalizeDetail({ nope: true }, "폴백")).toBe("폴백");
    expect(normalizeDetail([1, null], "폴백")).toBe("폴백");
  });
});
