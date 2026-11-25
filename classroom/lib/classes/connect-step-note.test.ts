import { describe, expect, it } from "vitest";

import { connectStepNote } from "./connect-step-note";

describe("connectStepNote", () => {
  it("소유자에게는 말을 붙이지 않는다 — 버튼이 있다", () => {
    expect(connectStepNote("owner")).toBeNull();
  });

  it("공동 강사에게는 누가 넣는지 말한다", () => {
    expect(connectStepNote("co_instructor")).toBe("소유자만 넣을 수 있습니다");
  });
});
