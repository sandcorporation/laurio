import { describe, expect, it } from "vitest";

import { achievementTone, describeAchievementRate, formatAchievementRate, formatPassedPerfect } from "./achievement";

describe("달성률 표시 문구", () => {
  it("참여자가 있으면 「비율 · 통과/전체명」으로 쓴다", () => {
    expect(formatAchievementRate({ passed_count: 5, member_count: 12, pass_rate: 5 / 12 })).toBe("42% · 5/12명");
  });

  it("아무도 못 풀었으면 0% 다 — 참여자가 없는 것과 구별한다", () => {
    expect(formatAchievementRate({ passed_count: 0, member_count: 5, pass_rate: 0 })).toBe("0% · 0/5명");
  });

  it("참여자가 0명이면 값 대신 「—」 를 쓴다", () => {
    expect(formatAchievementRate({ passed_count: 0, member_count: 0, pass_rate: null })).toBe("—");
  });

  it("참여자는 있는데 채점된 시도가 없으면 「—」 이고 까닭이 다르다(#1400)", () => {
    const ungraded = { passed_count: 0, member_count: 5, pass_rate: null };
    expect(formatAchievementRate(ungraded)).toBe("—");
    expect(describeAchievementRate(ungraded)).toBe("달성률 채점된 시도 없음");
  });

  it("「—」 는 읽기 도구에 이유를 따로 말한다", () => {
    expect(describeAchievementRate({ passed_count: 0, member_count: 0, pass_rate: null })).toBe("달성률 참여자 없음");
    expect(describeAchievementRate({ passed_count: 5, member_count: 12, pass_rate: 5 / 12 })).toBe(
      "달성률 42% · 5/12명",
    );
  });
});

describe("achievementTone (#633)", () => {
  it("60% 이상 verified · 30% 미만 attention · 사이 ink", () => {
    expect(achievementTone(0.6)).toBe("verified");
    expect(achievementTone(0.92)).toBe("verified");
    expect(achievementTone(0.29)).toBe("attention");
    expect(achievementTone(0)).toBe("attention");
    expect(achievementTone(0.3)).toBe("ink");
    expect(achievementTone(0.59)).toBe("ink");
  });
});

describe("formatPassedPerfect (#964)", () => {
  it("완벽 수가 있으면 「통과 n명 · 완벽 n명」", () => {
    expect(formatPassedPerfect({ passed_count: 5, perfect_count: 2 })).toBe("통과 5명 · 완벽 2명");
    expect(formatPassedPerfect({ passed_count: 0, perfect_count: 0 })).toBe("통과 0명 · 완벽 0명");
  });

  it("심화 항목이 없는 문제(null·없음)는 「완벽」을 빼고 통과만", () => {
    expect(formatPassedPerfect({ passed_count: 5, perfect_count: null })).toBe("통과 5명");
    expect(formatPassedPerfect({ passed_count: 5 })).toBe("통과 5명");
  });
});
