// 추론 강도 칸 표시 여부 순수 함수 시임(#402).
import { describe, expect, it } from "vitest";

import { isSelectedModelReasoning } from "./reasoning";
import type { ScoringModelRow } from "./api";

const MODELS: ScoringModelRow[] = [
  { id: "gpt-5-mini", label: "GPT-5 mini", context_window: 400_000, is_reasoning_model: true },
  { id: "gpt-4.1-mini", label: "GPT-4.1 mini", context_window: 1_047_576, is_reasoning_model: false },
];

describe("isSelectedModelReasoning", () => {
  it("카탈로그에 있는 추론 모델 id는 참이다", () => {
    expect(isSelectedModelReasoning("gpt-5-mini", MODELS, false)).toBe(true);
  });

  it("카탈로그에 있는 비추론 모델 id는 거짓이다", () => {
    expect(isSelectedModelReasoning("gpt-4.1-mini", MODELS, true)).toBe(false);
  });

  it("빈 문자열(클래스 기본값을 따름)은 클래스의 default_model_is_reasoning을 그대로 쓴다", () => {
    expect(isSelectedModelReasoning("", MODELS, true)).toBe(true);
    expect(isSelectedModelReasoning("", MODELS, false)).toBe(false);
  });

  it("카탈로그에 없는 id는 거짓으로 본다", () => {
    expect(isSelectedModelReasoning("gpt-6", MODELS, true)).toBe(false);
  });
});
