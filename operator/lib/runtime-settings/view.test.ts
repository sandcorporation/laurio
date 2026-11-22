import { describe, expect, it } from "vitest";

import type { RuntimeSetting, RuntimeSettingChange } from "./types";
import {
  accountRefusalText,
  canClear,
  canProbe,
  canConfirm,
  changeText,
  changedDateText,
  confirmedText,
  choiceOptions,
  initialInput,
  inputAttributes,
  savePayload,
  secretSummary,
  valueSummary,
  settingsOfTab,
  policyFieldsOfTab,
  tabFromParam,
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
    choices: null,
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

describe("선택형 설정(#994)", () => {
  const vendor = setting({
    key: "LLM_SCORING_VENDOR",
    label: "채점 벤더",
    kind: "choice",
    value: null,
    default: "openai",
    last4: null,
    choices: ["openai", "anthropic"],
  });

  it("선택 상자는 「—」 다음에 받는 값을 이름으로 보인다", () => {
    expect(choiceOptions(vendor)).toEqual([
      { value: "", label: "—" },
      { value: "openai", label: "OpenAI (Codex)" },
      { value: "anthropic", label: "Anthropic (Claude Code)" },
    ]);
  });

  it("선택형이 아니면 선택 상자가 없다", () => {
    expect(choiceOptions(setting())).toBeNull();
  });

  it("값이 없으면 기본값을 보이고 연결 시험이 없다", () => {
    expect(valueSummary(vendor)).toBe("기본 openai");
    expect(canProbe(vendor)).toBe(false);
  });
});

describe("탭(#1033)", () => {
  const all = ["LLM_OPENAI_TEMPERATURE", "REPOSITORY_DOWNLOAD_LIMIT_MB", "CONTEST_AI_QUALITY_REVIEW", "LLM_SCORING_VENDOR", "NEW_KEY"].map(
    (key) => setting({ key }),
  );

  it("탭은 정한 순서로 설정을 모으고 나머지는 기타로 간다", () => {
    expect(settingsOfTab(all, "ai").map((s) => s.key)).toEqual(["LLM_SCORING_VENDOR", "CONTEST_AI_QUALITY_REVIEW"]);
    expect(settingsOfTab(all, "limits").map((s) => s.key)).toEqual(["REPOSITORY_DOWNLOAD_LIMIT_MB"]);
    expect(settingsOfTab(all, "etc").map((s) => s.key)).toEqual(["LLM_OPENAI_TEMPERATURE", "NEW_KEY"]);
  });

  it("주소의 탭 값이 없거나 모르면 첫 탭이다", () => {
    expect(tabFromParam("limits")).toBe("limits");
    expect(tabFromParam(null)).toBe("ai");
    expect(tabFromParam("zzz")).toBe("ai");
  });

  it("채점 방식 값은 뜻을 말한다", () => {
    const method = setting({ key: "CONTEST_SCORING_METHOD", kind: "choice", choices: ["single_call", "agent"] });
    expect(choiceOptions(method)?.map((o) => o.label)).toEqual(["—", "한 번 호출", "에이전트"]);
    const pipeline = setting({ key: "CLASSROOM_SCORING_PIPELINE", kind: "choice", choices: ["single_call", "staged"] });
    expect(choiceOptions(pipeline)?.map((o) => o.label)).toEqual(["—", "한 번 호출", "기계 판정 먼저"]);
  });
});

describe("정책 탭(#1041)", () => {
  it("상한 탭에는 크기·개수 정책 칸 여섯이, 수수료·세금 탭에는 요율 칸 넷이 선다", () => {
    expect(policyFieldsOfTab("limits")).toContain("max_source_asset_bytes");
    expect(policyFieldsOfTab("limits")).toHaveLength(6);
    expect(policyFieldsOfTab("fees")).toEqual([
      "platform_fee_bps",
      "withholding_tax_bps",
      "withholding_necessary_expense_bps",
      "withholding_minor_income_exempt_won",
    ]);
    expect(policyFieldsOfTab("ai")).toEqual([]);
  });

  it("저장소 다운로드 상한은 소스 업로드 상한과 같은 탭이다", () => {
    const rows = [setting({ key: "REPOSITORY_DOWNLOAD_LIMIT_MB" })];
    expect(settingsOfTab(rows, "limits")).toHaveLength(1);
    expect(tabFromParam("fees")).toBe("fees");
  });
});

describe("마지막 계정 거절(#1058)", () => {
  it("기록이 없으면 칸을 그리지 않는다", () => {
    expect(accountRefusalText(null)).toBeNull();
  });

  it("시각·벤더·종류를 한 줄로 보인다", () => {
    expect(accountRefusalText({ at: "2026-11-19T21:44:00Z", vendor: "anthropic", kind: "usage_limit" })).toBe(
      "2026. 11. 20. 오전 6:44:00 · Anthropic · 사용 한도",
    );
  });

  it("모르는 벤더·종류는 이름 그대로 보인다", () => {
    expect(accountRefusalText({ at: "2026-11-19T21:44:00Z", vendor: "x", kind: "y" })).toContain("x · y");
  });
});

describe("스위치의 바뀐 날짜와 「이대로 둔다」(#1221)", () => {
  const sw = (overrides: Partial<RuntimeSetting> = {}) =>
    setting({ key: "CONTEST_AI_SCORING", kind: "switch", value: "on", default: "off", ...overrides });

  it("바뀐 날짜는 스위치에만, 서울 시각으로 보인다", () => {
    expect(changedDateText(sw({ changed_at: "2026-11-19T20:39:00Z" }))).toContain("2026. 11. 20.");
    expect(changedDateText(sw())).toBeNull();
    expect(changedDateText(setting({ kind: "text", changed_at: "2026-11-19T20:39:00Z" }))).toBeNull();
  });

  it("확인 버튼은 상위 등급이 경보 대상 스위치를 볼 때만", () => {
    expect(canConfirm(sw({ needs_confirm: true }), true)).toBe(true);
    expect(canConfirm(sw({ needs_confirm: true }), false)).toBe(false);
    expect(canConfirm(sw({ needs_confirm: false }), true)).toBe(false);
    expect(canConfirm(setting({ needs_confirm: true }), true)).toBe(false);
  });

  it("확인 기록은 누가·언제, 이력은 「이대로 둔다」", () => {
    expect(confirmedText(sw({ confirmed_at: "2026-11-21T03:03:00Z", confirmed_by: "boss" }))).toContain("boss");
    expect(confirmedText(sw())).toBeNull();
    expect(
      changeText({ id: 1, key: "K", label: "L", action: "ack", before: "on", after: "on", operator_username: "a", changed_at: "2026-11-21T00:00:00Z" }),
    ).toBe("이대로 둔다 · on");
  });
});
