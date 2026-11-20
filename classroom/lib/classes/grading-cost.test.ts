import { describe, expect, it } from "vitest";

import { NO_MEASUREMENT, perSubmissionCost, vendorLabel } from "./grading-cost";

describe("perSubmissionCost", () => {
  it("측정한 조합은 표의 숫자", () => {
    expect(perSubmissionCost("single", "gpt-4o-mini")).toBe("약 $0.01");
    expect(perSubmissionCost("single", "gpt-4.1-mini")).toBe("$0.03~0.13");
    expect(perSubmissionCost("agent", "claude-sonnet-5-5")).toBe("$0.07~0.17");
    expect(perSubmissionCost("agent", "claude-haiku-5-5")).toBe("$0.01~0.03");
  });
  it("표에 없는 조합·모델은 측정 없음", () => {
    expect(perSubmissionCost("single", "claude-sonnet-5-5")).toBe(NO_MEASUREMENT);
    expect(perSubmissionCost("agent", "gpt-4o-mini")).toBe(NO_MEASUREMENT);
    expect(perSubmissionCost("single", "other")).toBe(NO_MEASUREMENT);
  });
});

describe("vendorLabel", () => {
  it("키 종류로 벤더를 정하고 호환 서버는 없다", () => {
    expect(vendorLabel("openai_key")).toBe("OpenAI");
    expect(vendorLabel("anthropic_key")).toBe("Claude");
    expect(vendorLabel("compatible_server")).toBeNull();
  });
});
