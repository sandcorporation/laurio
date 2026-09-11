import { describe, expect, it } from "vitest";

import { isDeleteConfirmationTyped } from "./delete-confirmation";

describe("isDeleteConfirmationTyped", () => {
  it("정확히 같은 이름을 치면 확인된다", () => {
    expect(isDeleteConfirmationTyped("웹 스터디", "웹 스터디")).toBe(true);
  });

  it("앞뒤 공백은 무시한다", () => {
    expect(isDeleteConfirmationTyped("웹 스터디", "  웹 스터디  ")).toBe(true);
  });

  it("빈 입력은 확인되지 않는다", () => {
    expect(isDeleteConfirmationTyped("웹 스터디", "")).toBe(false);
  });

  it("부분 일치는 확인되지 않는다", () => {
    expect(isDeleteConfirmationTyped("웹 스터디", "웹")).toBe(false);
  });

  it("대소문자가 다르면 확인되지 않는다", () => {
    expect(isDeleteConfirmationTyped("React Study", "react study")).toBe(false);
  });
});
