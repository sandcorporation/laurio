import { describe, expect, it } from "vitest";

import { vendorLabel } from "./grading-cost";

describe("vendorLabel", () => {
  it("키 종류로 벤더를 정하고 호환 서버는 없다", () => {
    expect(vendorLabel("openai_key")).toBe("OpenAI");
    expect(vendorLabel("anthropic_key")).toBe("Claude");
    expect(vendorLabel("compatible_server")).toBeNull();
  });
});
