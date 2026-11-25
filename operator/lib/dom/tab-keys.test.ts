import { describe, expect, it } from "vitest";

import { nextTabIndex } from "./tab-keys";

describe("nextTabIndex", () => {
  it("←/→ 는 끝에서 돌아간다", () => {
    expect(nextTabIndex("ArrowRight", 0, 3)).toBe(1);
    expect(nextTabIndex("ArrowRight", 2, 3)).toBe(0);
    expect(nextTabIndex("ArrowLeft", 0, 3)).toBe(2);
    expect(nextTabIndex("ArrowLeft", 2, 3)).toBe(1);
  });
  it("Home/End 는 처음·끝", () => {
    expect(nextTabIndex("Home", 2, 3)).toBe(0);
    expect(nextTabIndex("End", 0, 3)).toBe(2);
  });
  it("↑↓·다른 키·빈 목록은 null", () => {
    expect(nextTabIndex("ArrowDown", 0, 3)).toBeNull();
    expect(nextTabIndex("a", 0, 3)).toBeNull();
    expect(nextTabIndex("ArrowRight", 0, 0)).toBeNull();
  });
});
