// 채점 지침 단계 → 화면 문장 순수 함수 시임(#386, 부모 #385).
import { describe, expect, it } from "vitest";

import {
  GRADING_STRICTNESS_OPTIONS,
  gradingGuidelineText,
  gradingStrictnessLabel,
} from "./grading-guideline";

describe("gradingStrictnessLabel", () => {
  it("네 단계 각각의 화면 라벨을 낸다", () => {
    expect(gradingStrictnessLabel("strict")).toBe("엄격");
    expect(gradingStrictnessLabel("normal")).toBe("보통");
    expect(gradingStrictnessLabel("lenient")).toBe("관대");
    expect(gradingStrictnessLabel("custom")).toBe("직접 입력");
  });
});

describe("gradingGuidelineText", () => {
  it("엄격은 글자 그대로 일치를 요구하는 문장을 낸다", () => {
    expect(gradingGuidelineText("strict", "")).toContain("글자 그대로 일치");
  });

  it("보통은 표기 차이를 봐준다는 문장을 낸다", () => {
    expect(gradingGuidelineText("normal", "")).toContain("표기 차이는 봐줍니다");
  });

  it("관대는 핵심 동작만 본다는 문장을 낸다", () => {
    expect(gradingGuidelineText("lenient", "")).toContain("핵심 동작이 되면 충족");
  });

  it("직접 입력은 강사가 쓴 문장을 그대로 낸다", () => {
    expect(gradingGuidelineText("custom", "함수 이름은 solve 여야 한다")).toBe(
      "함수 이름은 solve 여야 한다",
    );
  });

  it("네 단계 각각 다른 문장을 낸다 — 프리셋 셋이 서로 뒤섞이지 않는다", () => {
    const texts = GRADING_STRICTNESS_OPTIONS.filter((o) => o.value !== "custom").map((o) =>
      gradingGuidelineText(o.value, ""),
    );
    expect(new Set(texts).size).toBe(texts.length);
  });
});
