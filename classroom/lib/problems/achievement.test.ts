import { describe, expect, it } from "vitest";

import { describeAchievementRate, formatAchievementRate } from "./achievement";

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

  it("「—」 는 읽기 도구에 이유를 따로 말한다", () => {
    expect(describeAchievementRate({ passed_count: 0, member_count: 0, pass_rate: null })).toBe("달성률 참여자 없음");
    expect(describeAchievementRate({ passed_count: 5, member_count: 12, pass_rate: 5 / 12 })).toBe(
      "달성률 42% · 5/12명",
    );
  });
});
