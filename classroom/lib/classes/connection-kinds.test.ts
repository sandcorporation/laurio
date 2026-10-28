import { describe, expect, it } from "vitest";

import { connectionKindOptions, initialConnectionKind } from "./connection-kinds";

describe("채점 연결 선택지", () => {
  it("시행일 전에는 Claude(Anthropic) 키가 없다", () => {
    expect(connectionKindOptions(false).map((o) => o.kind)).toEqual(["openai_key", "compatible_server"]);
  });
  it("시행일이 지나면 셋이다", () => {
    expect(connectionKindOptions(true).map((o) => o.kind)).toEqual(["openai_key", "anthropic_key", "compatible_server"]);
  });
  it("선택지에 없는 지금 종류는 OpenAI 키로 시작한다", () => {
    expect(initialConnectionKind("anthropic_key", false)).toBe("openai_key");
    expect(initialConnectionKind("anthropic_key", true)).toBe("anthropic_key");
    expect(initialConnectionKind("compatible_server", false)).toBe("compatible_server");
  });
});
