import { describe, expect, it } from "vitest";

import { connectionKindOptions, initialConnectionKind, vendorKeyButtonName, vendorUnavailableReason } from "./connection-kinds";

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

describe("꺼진 벤더 선택지의 이유", () => {
  it("키가 없으면 「키 없음」, 거부되면 「키 거부됨」, 고를 수 있으면 없다", () => {
    expect(vendorUnavailableReason(null)).toBe("키 없음");
    expect(vendorUnavailableReason({ switchable: false })).toBe("키 거부됨");
    expect(vendorUnavailableReason({ switchable: true })).toBeNull();
  });
  it("키 줄 단추 이름은 보이는 글자를 포함하고 키 이름을 앞에 둔다", () => {
    expect(vendorKeyButtonName("OpenAI 키", "넣기")).toBe("OpenAI 키 넣기");
  });
});
