import { describe, expect, it } from "vitest";

import { WAITING_BADGE_LABEL, daysWaitingLabel, waitingBadgeLabel, whoseTurn } from "./payout-waiting";

describe("무엇을 기다리나 — 세 대기의 문구가 서로 다르다 (#422 AC)", () => {
  it("신원·셀러·이체 배지 문구가 셋 다 다르다", () => {
    const labels = Object.values(WAITING_BADGE_LABEL);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("모르는 blocked_on 은 값 그대로를 보여준다", () => {
    expect(waitingBadgeLabel("operator")).toBe("operator");
  });

  it("주의색을 암시하는 낱말(실패·오류·경고)을 쓰지 않는다 — 대기는 실패가 아니다", () => {
    for (const label of Object.values(WAITING_BADGE_LABEL)) {
      expect(label).not.toMatch(/실패|오류|경고/);
    }
  });
});

describe("누구 차례 (#422 AC, ADR-0020)", () => {
  it("신원 대기는 개발자 차례다", () => {
    expect(whoseTurn("identity", null, false)).toContain("개발자 차례");
  });

  it("셀러 대기(재시도 중)는 지급대행사 차례다", () => {
    expect(whoseTurn("seller", "retrying", false)).toContain("지급대행사 차례");
  });

  it("셀러 대기(자동 재시도 실패)는 운영자 차례다", () => {
    expect(whoseTurn("seller", "stuck", false)).toContain("운영자 차례");
  });

  it("이체 대기는 운영자 차례다", () => {
    expect(whoseTurn("transfer", null, false)).toContain("운영자 차례");
  });

  it("operator_actionable 이면 무엇을 기다리든 운영자 차례다", () => {
    expect(whoseTurn("identity", null, true)).toContain("운영자 차례");
    expect(whoseTurn("seller", "retrying", true)).toContain("운영자 차례");
  });

  it("정의되지 않은 조합도 운영자 차례다", () => {
    expect(whoseTurn("operator", null, false)).toContain("운영자 차례");
  });

  it("세 기본 대기의 「누구 차례」 문구가 서로 다르다", () => {
    const turns = [
      whoseTurn("identity", null, false),
      whoseTurn("seller", "retrying", false),
      whoseTurn("transfer", null, false),
    ];
    expect(new Set(turns).size).toBe(turns.length);
  });
});

describe("며칠째 (#422 AC user story 16)", () => {
  it("오늘 생긴 것은 '오늘'이다", () => {
    expect(daysWaitingLabel(new Date().toISOString())).toBe("오늘");
  });

  it("N일 전이면 'N일째'다", () => {
    const threeDaysAgo = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString();
    expect(daysWaitingLabel(threeDaysAgo)).toBe("3일째");
  });
});
