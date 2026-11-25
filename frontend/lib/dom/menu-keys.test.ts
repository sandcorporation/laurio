import { describe, expect, it } from "vitest";

import { nextMenuIndex } from "./menu-keys";

describe("nextMenuIndex", () => {
  it("↑↓ 는 끝에서 돌아간다", () => {
    expect(nextMenuIndex("ArrowDown", 0, 3)).toBe(1);
    expect(nextMenuIndex("ArrowDown", 2, 3)).toBe(0);
    expect(nextMenuIndex("ArrowUp", 0, 3)).toBe(2);
    expect(nextMenuIndex("ArrowUp", 2, 3)).toBe(1);
  });
  it("Home/End 는 처음·끝", () => {
    expect(nextMenuIndex("Home", 2, 3)).toBe(0);
    expect(nextMenuIndex("End", 0, 3)).toBe(2);
  });
  it("다른 키·빈 메뉴는 null", () => {
    expect(nextMenuIndex("a", 0, 3)).toBeNull();
    expect(nextMenuIndex("ArrowDown", 0, 0)).toBeNull();
  });
});
