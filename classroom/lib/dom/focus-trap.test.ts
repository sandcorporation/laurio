import { describe, expect, it } from "vitest";

import { trapTabTarget } from "./focus-trap";

describe("trapTabTarget", () => {
  it("끝에서 Tab 은 처음으로, 처음에서 Shift+Tab 은 끝으로", () => {
    expect(trapTabTarget(false, 1, 2)).toBe(0);
    expect(trapTabTarget(true, 0, 2)).toBe(1);
  });
  it("창 안에서는 브라우저에 맡긴다", () => {
    expect(trapTabTarget(false, 0, 2)).toBeNull();
    expect(trapTabTarget(true, 1, 2)).toBeNull();
  });
  it("초점이 창 밖이면 끌어들인다", () => {
    expect(trapTabTarget(false, -1, 2)).toBe(0);
    expect(trapTabTarget(true, -1, 2)).toBe(1);
  });
  it("항목이 하나면 계속 같은 곳", () => {
    expect(trapTabTarget(false, 0, 1)).toBe(0);
    expect(trapTabTarget(true, 0, 1)).toBe(0);
  });
});
