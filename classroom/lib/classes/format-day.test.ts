import { describe, expect, it } from "vitest";

import { formatDay } from "./format-day";

describe("formatDay", () => {
  it("월/일만 앞자리 0 없이 적는다", () => {
    expect(formatDay("2026-03-05T12:00:00")).toBe("3/5");
    expect(formatDay("2026-10-14T09:00:00")).toBe("10/14");
  });
});
