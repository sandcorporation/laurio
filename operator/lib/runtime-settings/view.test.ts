import { describe, expect, it } from "vitest";

import type { RuntimeSetting, RuntimeSettingChange } from "./types";
import {
  canClear,
  canProbe,
  changeText,
  initialInput,
  inputAttributes,
  savePayload,
  secretSummary,
  valueSummary,
} from "./view";

function setting(overrides: Partial<RuntimeSetting> = {}): RuntimeSetting {
  return {
    key: "OPEN_AI_API_KEY",
    label: "OpenAI API 키",
    kind: "secret",
    source: "db",
    configured: true,
    value: null,
    default: null,
    last4: "abcd",
    updated_at: "2026-11-05T12:00:00Z",
    updated_by: "su",
    ...overrides,
  };
}

describe("비밀 입력은 쓰기 전용이다", () => {
  it("설정된 키도 입력칸은 빈칸에서 시작한다", () => {
    expect(initialInput(setting())).toBe("");
  });

  it("비밀 입력칸은 글자가 보이지 않고 브라우저가 기억하지 않는다", () => {
    expect(inputAttributes(setting())).toMatchObject({ type: "password", autoComplete: "new-password" });
    expect(inputAttributes(setting({ kind: "text", key: "LLM_OPENAI_MODEL" })).type).toBe("text");
  });
});

describe("끝 4자리 표시", () => {
  it("설정된 키는 「설정됨 · ••••abcd」", () => {
    expect(secretSummary(setting())).toBe("설정됨 · ••••abcd");
    expect(valueSummary(setting({ source: "env", last4: "wxyz" }))).toBe("설정됨 · ••••wxyz");
  });

  it("짧은 키는 끝자리 없이 「설정됨」, 없으면 「설정 안 됨」", () => {
    expect(secretSummary(setting({ last4: "" }))).toBe("설정됨");
    expect(secretSummary(setting({ configured: false, source: "none", last4: null }))).toBe("설정 안 됨");
  });

  it("비밀이 아닌 설정은 값 그대로, 없으면 —", () => {
    expect(valueSummary(setting({ kind: "float", value: "0.2", last4: null }))).toBe("0.2");
    expect(valueSummary(setting({ kind: "text", value: null, last4: null, source: "none" }))).toBe("—");
    expect(valueSummary(setting({ kind: "float", value: null, default: "0.7", last4: null, source: "none" }))).toBe(
      "기본 0.7",
    );
  });
});

describe("비운 저장은 기존 값을 유지한다", () => {
  it("공백만 있는 입력은 보내지 않는다", () => {
    expect(savePayload("")).toBeNull();
    expect(savePayload("   ")).toBeNull();
  });

  it("값은 앞뒤 공백을 걷어 보낸다", () => {
    expect(savePayload("  gpt-4o  ")).toEqual({ value: "gpt-4o" });
  });
});

describe("지우기", () => {
  it("DB 에 값이 있을 때만 지울 수 있다(지우면 env 로 돌아간다)", () => {
    expect(canClear(setting({ source: "db" }))).toBe(true);
    expect(canClear(setting({ source: "env" }))).toBe(false);
    expect(canClear(setting({ source: "none" }))).toBe(false);
  });

  it("연결 시험은 키에만 있다", () => {
    expect(canProbe(setting())).toBe(true);
    expect(canProbe(setting({ kind: "float" }))).toBe(false);
  });
});

describe("변경 이력 문구", () => {
  const base: RuntimeSettingChange = {
    id: 1,
    key: "OPEN_AI_API_KEY",
    label: "OpenAI API 키",
    action: "set",
    before: "",
    after: "••••abcd",
    operator_username: "su",
    changed_at: "2026-11-05T12:00:00Z",
  };

  it("저장은 이전 → 이후, 처음이면 — 에서", () => {
    expect(changeText(base)).toBe("— → ••••abcd");
    expect(changeText({ ...base, before: "••••abcd", after: "••••efgh" })).toBe("••••abcd → ••••efgh");
  });

  it("지우기는 지운 값을 보인다", () => {
    expect(changeText({ ...base, action: "clear", before: "••••efgh", after: "" })).toBe("지우기 · ••••efgh");
  });
});
