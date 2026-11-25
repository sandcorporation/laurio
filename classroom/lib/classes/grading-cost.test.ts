import { describe, expect, it } from "vitest";

import { agentBlockedNote, vendorLabel } from "./grading-cost";

describe("vendorLabel", () => {
  it("키 종류로 벤더를 정하고 호환 서버는 없다", () => {
    expect(vendorLabel("openai_key")).toBe("OpenAI");
    expect(vendorLabel("anthropic_key")).toBe("Claude");
    expect(vendorLabel("compatible_server")).toBeNull();
  });
});

describe("agentBlockedNote — 에이전트가 꺼진 까닭을 키와 모델로 가른다", () => {
  it("호환 서버 연결이면 키(연결) 까닭이다", () => {
    expect(agentBlockedNote({ keyReason: "compatible_server", modelBlocked: false })).toEqual({
      kind: "key",
      text: "호환 서버 연결에서는 에이전트를 쓸 수 없습니다.",
    });
  });
  it("연결은 되는데 기본 모델이 못 받으면 모델 까닭이다", () => {
    expect(agentBlockedNote({ keyReason: null, modelBlocked: true })).toEqual({
      kind: "model",
      text: "기본 모델이 gpt-5-mini 이상이어야 에이전트를 고를 수 있습니다.",
    });
  });
  it("둘 다면 키 까닭이 앞서고, 둘 다 아니면 없다", () => {
    expect(agentBlockedNote({ keyReason: "compatible_server", modelBlocked: true })?.kind).toBe("key");
    expect(agentBlockedNote({ keyReason: null, modelBlocked: false })).toBeNull();
  });
});
