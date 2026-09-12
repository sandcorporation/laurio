import { describe, expect, it } from "vitest";

import { PARTICIPATION_EMPTY_MESSAGE } from "./empty-state";

describe("PARTICIPATION_EMPTY_MESSAGE", () => {
  it("공모전·과제 어느 낱말도 쓰지 않는다 — 과제만 쓸 수 있는 사람도 이 화면을 연다 (#353)", () => {
    expect(PARTICIPATION_EMPTY_MESSAGE).not.toMatch(/공모전|과제/);
  });
});
