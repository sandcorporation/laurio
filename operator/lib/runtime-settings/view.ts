// 운영 설정 화면의 순수 규칙(#922) — vitest 가 이 파일만 본다(react 없이).

import type { ProbeResult, RuntimeSetting, RuntimeSettingChange, RuntimeSettingSource } from "./types";

export const MASK = "••••";

export const SOURCE_LABELS: Record<RuntimeSettingSource, string> = {
  db: "DB",
  env: "env",
  none: "없음",
};

export const PROBE_LABELS: Record<ProbeResult, string> = {
  ok: "연결됨",
  invalid_key: "키 거절",
  unavailable: "확인 못 함",
};

/** 비밀 설정의 요약 — 「설정됨 · ••••abcd」. 키 원문은 이 화면에 오지도 않는다. */
export function secretSummary(setting: RuntimeSetting): string {
  if (!setting.configured) return "설정 안 됨";
  return setting.last4 ? `설정됨 · ${MASK}${setting.last4}` : "설정됨";
}

/** 표에 보일 지금 값 — 비밀이면 요약, 아니면 값(없으면 「—」). */
export function valueSummary(setting: RuntimeSetting): string {
  if (setting.kind === "secret") return secretSummary(setting);
  if (setting.value !== null) return setting.value;
  return setting.default !== null ? `기본 ${setting.default}` : "—";
}

/** 입력칸의 처음 값 — 비밀은 언제나 빈칸이다(쓰기 전용). 다른 설정도 빈칸에서 시작한다. */
export function initialInput(_setting: RuntimeSetting): string {
  return "";
}

/** 입력칸의 종류 — 비밀은 화면에 글자가 보이지 않고 브라우저가 기억하지 않는다. */
export function inputAttributes(setting: RuntimeSetting): {
  type: "password" | "text";
  autoComplete: "off" | "new-password";
  inputMode: "decimal" | "text";
} {
  if (setting.kind === "secret") return { type: "password", autoComplete: "new-password", inputMode: "text" };
  return { type: "text", autoComplete: "off", inputMode: setting.kind === "float" ? "decimal" : "text" };
}

const CHOICE_LABELS: Record<string, string> = {
  openai: "OpenAI (Codex)",
  anthropic: "Anthropic (Claude Code)",
  single_call: "한 번 호출",
  agent: "에이전트",
};

/** 선택 상자의 항목(#994) — `choice` 가 아니면 null. 첫 항목 「—」는 고르지 않음(저장하지 않는다). */
export function choiceOptions(setting: RuntimeSetting): { value: string; label: string }[] | null {
  if (setting.kind !== "choice" || !setting.choices) return null;
  return [
    { value: "", label: "—" },
    ...setting.choices.map((value) => ({ value, label: CHOICE_LABELS[value] ?? value })),
  ];
}

/** 저장할 본문 — 비운 입력은 보내지 않는다(기존 값 유지). */
export function savePayload(input: string): { value: string } | null {
  const value = input.trim();
  return value === "" ? null : { value };
}

/** 「지우기」는 DB 에 값이 있을 때만 — 지우면 env 로 돌아간다. */
export function canClear(setting: RuntimeSetting): boolean {
  return setting.source === "db";
}

export function canProbe(setting: RuntimeSetting): boolean {
  return setting.kind === "secret";
}

export function changeText(change: RuntimeSettingChange): string {
  if (change.action === "clear") return `지우기 · ${change.before || "—"}`;
  return `${change.before || "—"} → ${change.after}`;
}

/** DB 값의 변경 시각·변경자 — DB 값이 없으면 null(줄을 그리지 않는다). */
export function updatedText(setting: RuntimeSetting): string | null {
  if (!setting.updated_at) return null;
  return `${new Date(setting.updated_at).toLocaleString("ko-KR")} · ${setting.updated_by ?? ""}`;
}

export type SettingsTabId = "ai" | "limits" | "etc";

export const SETTINGS_TABS: { id: SettingsTabId; label: string; keys: readonly string[] }[] = [
  {
    id: "ai",
    label: "AI 채점",
    keys: [
      "LLM_SCORING_VENDOR",
      "CONTEST_SCORING_METHOD",
      "LLM_OPENAI_MODEL",
      "OPEN_AI_API_KEY",
      "LLM_ANTHROPIC_MODEL",
      "ANTHROPIC_API_KEY",
      "CONTEST_AI_SCORING",
      "CONTEST_AI_QUALITY_REVIEW",
      "AGENT_SCORING_DAILY_LIMIT_USD",
    ],
  },
  { id: "limits", label: "한도", keys: ["REPOSITORY_DOWNLOAD_LIMIT_MB"] },
  { id: "etc", label: "기타", keys: [] },
];

/** 주소의 `?tab=` 값 → 탭. 모르는 값·없는 값은 첫 탭. */
export function tabFromParam(param: string | null): SettingsTabId {
  return SETTINGS_TABS.find((tab) => tab.id === param)?.id ?? SETTINGS_TABS[0].id;
}

/** 탭에 속한 설정 — 「AI 채점」·「한도」는 정한 순서대로, 「기타」는 어느 탭에도 없는 나머지(새 키가 사라지지 않는다). */
export function settingsOfTab(settings: RuntimeSetting[], tab: SettingsTabId): RuntimeSetting[] {
  const named = SETTINGS_TABS.flatMap((t) => t.keys);
  if (tab === "etc") return settings.filter((setting) => !named.includes(setting.key));
  const keys = SETTINGS_TABS.find((t) => t.id === tab)?.keys ?? [];
  return keys.flatMap((key) => settings.filter((setting) => setting.key === key));
}
