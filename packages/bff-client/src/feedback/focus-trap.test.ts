import { describe, expect, it } from "vitest";

import { trapTabTarget } from "./focus-trap";

describe("trapTabTarget", () => {
  it("끝에서 Tab 은 처음으로, 처음에서 Shift+Tab 은 끝으로", () => {
    expect(trapTabTarget(false, 2, 3)).toBe(0);
    expect(trapTabTarget(true, 0, 3)).toBe(2);
  });
  it("창 안에서 움직이면 브라우저에 맡긴다", () => {
    expect(trapTabTarget(false, 0, 3)).toBeNull();
    expect(trapTabTarget(true, 2, 3)).toBeNull();
  });
  it("초점이 창 밖이면 가장자리로 끌어들이고, 대상이 없으면 맡긴다", () => {
    expect(trapTabTarget(false, -1, 3)).toBe(0);
    expect(trapTabTarget(true, -1, 3)).toBe(2);
    expect(trapTabTarget(false, -1, 0)).toBeNull();
  });
});
