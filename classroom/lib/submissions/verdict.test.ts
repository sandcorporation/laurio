import { describe, expect, it } from "vitest";

import { VERDICT_LABEL, verdictFromMet, verdictMarkerClass, verdictOf } from "./verdict";

describe("verdictOf", () => {
  it("서버가 실은 세 값을 그대로 읽는다", () => {
    expect(verdictOf({ is_met: true, verdict: "met" })).toBe("met");
    expect(verdictOf({ is_met: false, verdict: "unmet" })).toBe("unmet");
    expect(verdictOf({ is_met: false, verdict: "unverifiable" })).toBe("unverifiable");
  });

  it("verdict 가 없는 옛 모양은 is_met 에서 읽는다", () => {
    expect(verdictOf({ is_met: true })).toBe("met");
    expect(verdictOf({ is_met: false })).toBe("unmet");
    expect(verdictOf({ is_met: false, verdict: null })).toBe("unmet");
  });
});

describe("표시", () => {
  it("세 값의 라벨", () => {
    expect([VERDICT_LABEL.met, VERDICT_LABEL.unmet, VERDICT_LABEL.unverifiable]).toEqual(["충족", "미충족", "확인 불가"]);
  });

  it("확인 불가의 표식은 미충족·판정 없음과 다르고 새 색을 쓰지 않는다", () => {
    const marks = [null, "met", "unmet", "unverifiable"].map((v) => verdictMarkerClass(v as never));
    expect(new Set(marks).size).toBe(4);
    expect(verdictMarkerClass("unverifiable")).toBe("border-dashed border-ink/45");
    expect(verdictFromMet(true)).toBe("met");
    expect(verdictFromMet(false)).toBe("unmet");
  });
});
