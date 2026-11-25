import { describe, expect, it } from "vitest";

import { unpassedBadge } from "./unpassed-badge";

describe("unpassedBadge", () => {
  it("한 번도 안 냈으면 목록과 같은 「미제출」", () => {
    expect(unpassedBadge(0)).toEqual({ label: "미제출", tone: "neutral" });
  });

  it("냈는데 통과하지 못했으면 「미통과」", () => {
    expect(unpassedBadge(2)).toEqual({ label: "미통과", tone: "error" });
  });
});
