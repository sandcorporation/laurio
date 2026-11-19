import { describe, expect, it } from "vitest";
import { checklistSummaryLine, verdictGlyph, verdictStatusText } from "./checklist-summary";

const none = { total: 0, verdicts: [] as never[] };

describe("checklistSummaryLine", () => {
  it("통과 못 한 시도는 남은 필수 수를 먼저 말한다", () => {
    expect(
      checklistSummaryLine({
        judged: { passed: false, perfect: false },
        required: { met: 1, total: 2, unmetCount: 1 },
        advanced: { total: 1, verdicts: ["unmet"] },
        hidden: null,
        unverifiable: 0,
      }),
    ).toBe("통과까지 1개 남음 · 필수 1/2 · 심화 0/1");
  });

  it("통과·완벽은 앞말이 바뀐다", () => {
    const base = { required: { met: 2, total: 2, unmetCount: 0 }, advanced: none, hidden: null, unverifiable: 0 };
    expect(checklistSummaryLine({ ...base, judged: { passed: true, perfect: null } })).toBe("통과 · 필수 2/2");
    expect(checklistSummaryLine({ ...base, judged: { passed: true, perfect: true } })).toBe("완벽 · 필수 2/2");
  });

  it("숨은 심화 항목은 심화 분모·분자에 든다", () => {
    expect(
      checklistSummaryLine({
        judged: { passed: true, perfect: false },
        required: { met: 1, total: 1, unmetCount: 0 },
        advanced: { total: 1, verdicts: ["met"] },
        hidden: { total: 2, met: 1 },
        unverifiable: 0,
      }),
    ).toBe("통과 · 필수 1/1 · 심화 2/3");
  });

  it("필수가 하나도 없으면 필수 없음", () => {
    expect(
      checklistSummaryLine({
        judged: { passed: true, perfect: false },
        required: { met: 0, total: 0, unmetCount: 0 },
        advanced: { total: 1, verdicts: ["unmet"] },
        hidden: null,
        unverifiable: 0,
      }),
    ).toBe("통과 · 필수 없음 · 심화 0/1");
  });

  it("판정 전에는 개수만 말한다", () => {
    expect(
      checklistSummaryLine({
        judged: null,
        required: { met: null, total: 2, unmetCount: 0 },
        advanced: { total: 1, verdicts: [null] },
        hidden: null,
        unverifiable: 0,
      }),
    ).toBe("필수 2개 · 심화 1개");
    expect(
      checklistSummaryLine({ judged: null, required: { met: null, total: 2, unmetCount: 0 }, advanced: none, hidden: null, unverifiable: 0 }),
    ).toBe("필수 2개");
  });

  it("확인 불가가 있으면 그 수를 덧붙인다", () => {
    expect(
      checklistSummaryLine({
        judged: { passed: false, perfect: false },
        required: { met: 0, total: 1, unmetCount: 1 },
        advanced: none,
        hidden: null,
        unverifiable: 1,
      }),
    ).toBe("통과까지 1개 남음 · 필수 0/1 · 확인 불가 1개");
  });
});

describe("줄 표식", () => {
  it("상태를 글자와 모양으로 낸다", () => {
    expect(verdictStatusText("met", true)).toBe("통과");
    expect(verdictStatusText("unmet", true)).toBe("미통과");
    expect(verdictStatusText("unmet", false)).toBe("아직");
    expect(verdictStatusText("unverifiable", true)).toBe("확인 불가");
    expect(verdictStatusText(null, true)).toBe("아직");
    expect(verdictGlyph("met", true)).toBe("✓");
    expect(verdictGlyph("unmet", true)).toBe("✕");
    expect(verdictGlyph("unmet", false)).toBe("○");
    expect(verdictGlyph("unverifiable", false)).toBe("?");
  });
});
