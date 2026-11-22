import { describe, expect, it } from "vitest";

import {
  agentConnectionsLabel,
  agentOnlyLabel,
  calculatorPath,
  changeChoice,
  escalationCost,
  NO_MEASUREMENT,
  sourceLabel,
  spreadKrw,
  spreadSeconds,
} from "./calculator";

describe("calculatorPath", () => {
  it("빈 칸은 싣지 않는다", () => {
    expect(calculatorPath(7, {})).toBe("/api/backend/classroom/classes/7/scoring-calculator");
  });
  it("고른 칸을 쿼리로 싣는다", () => {
    expect(
      calculatorPath(7, { vendor: "anthropic", method: "agent", model: "claude-haiku-5-5", problemId: 3, source: "p90" }),
    ).toBe(
      "/api/backend/classroom/classes/7/scoring-calculator?vendor=anthropic&method=agent&model=claude-haiku-5-5&problem_id=3&source=p90",
    );
  });
});

describe("changeChoice", () => {
  it("프로바이더를 바꾸면 모델을 비운다", () => {
    expect(changeChoice({ vendor: "openai", model: "gpt-4.1-mini" }, "vendor", "anthropic")).toEqual({
      vendor: "anthropic",
      model: undefined,
    });
  });
  it("문제를 바꾸면 소스 크기를 비운다", () => {
    expect(changeChoice({ problemId: 1, source: "p90" }, "problemId", "2")).toEqual({ problemId: 2, source: undefined });
  });
});

describe("라벨", () => {
  it("에이전트 되는 연결은 받은 목록에서 읽는다", () => {
    expect(agentOnlyLabel(["anthropic"])).toBe("Claude 키만");
    expect(agentOnlyLabel(["openai", "anthropic"])).toBe("OpenAI·Claude 키만");
    expect(agentConnectionsLabel(["anthropic"])).toBe("Claude 키");
  });
  it("소스 크기는 이름과 글자 수", () => {
    expect(sourceLabel({ key: "medium", chars: 50_000 })).toBe("보통 · 5만 자");
    expect(sourceLabel({ key: "p90", chars: 6_120 })).toBe("제출 p90 · 6,120 자");
  });
  it("실측이 없으면 실측 없음", () => {
    expect(spreadKrw({ sample_count: 2, median: null, p90: null })).toBe(NO_MEASUREMENT);
    expect(spreadSeconds({ sample_count: 0, median: null, p90: null })).toBe(NO_MEASUREMENT);
  });
  it("실측이 있으면 중앙·p90", () => {
    expect(spreadKrw({ sample_count: 3, median: 45, p90: 120 })).toBe("중앙 약 45원 · p90 약 120원");
    expect(spreadSeconds({ sample_count: 3, median: 40, p90: 150 })).toBe("중앙 40초 · p90 2.5분");
  });
});

describe("escalationCost", () => {
  it("꺼졌으면 줄이 없다", () => {
    expect(escalationCost({ model_id: null, per_suspect: null, suspect_rate: null })).toBeNull();
  });
  it("고른 모델의 의심 한 건당 값과 실측 없는 비율", () => {
    expect(
      escalationCost({
        model_id: "gpt-4.1",
        per_suspect: { input_tokens: 1, output_tokens: 1, usd: 0.1, krw: 140, open_ended: false },
        suspect_rate: null,
      }),
    ).toEqual({ model: "gpt-4.1", perSuspect: expect.stringMatching(/^의심 한 건당 /), rate: NO_MEASUREMENT });
  });
});
