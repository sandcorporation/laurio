// 채점 비용 계산기(#1270·#1304·#1308) — 셈은 백엔드(`classroom.scoring_calculator`)가 하고, 여기는 바꿔 본 가정을 경로로 옮기고
// 받은 값을 화면 글자로 바꾼다. 숫자를 따로 적지 않는다.
import type { components } from "@codemit/bff-client";

import { formatKrw, formatManCount } from "./cost";

export type ScoringCalculator = components["schemas"]["ScoringCalculatorOut"];
export type CalculatorRow = components["schemas"]["ScoringCalculatorRowOut"];
export type CalculatorMethod = "single" | "agent";

/** 고른 칸과 바꿔 본 가정 — 빈 칸은 백엔드가 지금 이 클래스의 조합·기본 가정으로 채운다. */
export type CalculatorChoice = {
  vendor?: string;
  method?: CalculatorMethod;
  model?: string;
  problemId?: number;
  source?: string;
  sourceChars?: number;
  requirements?: number;
  suspectRate?: number;
};

/** 가정 칸 — 입력으로 바꿔 보는 것. */
export type AssumptionField = "sourceChars" | "requirements" | "suspectRate";

const QUERY_NAMES: [keyof CalculatorChoice, string][] = [
  ["vendor", "vendor"],
  ["method", "method"],
  ["model", "model"],
  ["problemId", "problem_id"],
  ["source", "source"],
  ["sourceChars", "source_chars"],
  ["requirements", "requirements"],
  ["suspectRate", "suspect_rate"],
];

export function calculatorPath(classId: number, choice: CalculatorChoice): string {
  const params = new URLSearchParams();
  for (const [field, name] of QUERY_NAMES) {
    const value = choice[field];
    if (value !== undefined && value !== "") params.set(name, String(value));
  }
  const query = params.toString();
  return `/api/backend/classroom/classes/${classId}/scoring-calculator${query ? `?${query}` : ""}`;
}

/** 한 칸을 바꾼다 — 문제를 바꾸면 소스 크기·항목 수를, 소스 크기를 고르면 입력한 글자 수를 비워 그 선택지의 처음 값으로 간다. */
export function changeChoice(
  current: CalculatorChoice,
  field: keyof CalculatorChoice,
  value: string | number | undefined,
): CalculatorChoice {
  if (field === "problemId") {
    return { ...current, problemId: Number(value), source: undefined, sourceChars: undefined, requirements: undefined };
  }
  if (field === "source") return { ...current, source: String(value), sourceChars: undefined };
  if (field === "method") return { ...current, method: value === "agent" ? "agent" : "single" };
  if (field === "vendor") return { ...current, vendor: String(value), model: undefined };
  if (value === undefined) return { ...current, [field]: undefined };
  if (field === "model") return { ...current, model: String(value) };
  return { ...current, [field]: Number(value) };
}

/** 입력 칸의 글자를 가정 값으로 — 비었거나 숫자가 아니면 `undefined`(기본값으로 돌아간다). */
export function parseAssumption(text: string): number | undefined {
  const trimmed = text.trim().replace(/,/g, "");
  if (trimmed === "") return undefined;
  const value = Number(trimmed);
  return Number.isFinite(value) && value >= 0 ? value : undefined;
}

const VENDOR_LABEL: Record<string, string> = { openai: "OpenAI", anthropic: "Claude" };

export function providerLabel(vendor: string): string {
  return VENDOR_LABEL[vendor] ?? vendor;
}

/** 소스 파일 수 — 천 단위로 끊어 쓴다. */
export function fileCount(files: number): string {
  return files.toLocaleString("ko-KR");
}

/** 파일 수 옆에 보이는 글자 수 — 「3.2만 자」. */
export function charsLabel(chars: number): string {
  return `${formatManCount(chars)} 자`;
}

export const HOLD_TEXT = "담지 못함 — 보류";

/** 고른 칸의 행 — 처음 값은 지금 이 클래스의 조합이다. */
export function selectedRow(calc: ScoringCalculator): CalculatorRow | undefined {
  return calc.rows.find((r) => r.model_id === calc.selection.model_id);
}

/**
 * 「제출 한 건」 — 고른 칸의 예상 금액. 한 번 호출이 입력 크기를 담지 못하면 보류 글자다.
 * 새 채점기가 켜져 있고 이 클래스에 재판정 모델이 있으면 그 몫을 같은 금액에 합친다(줄을 따로 두지 않는다).
 */
export function submissionAmount(calc: ScoringCalculator): string {
  const row = selectedRow(calc);
  if (!row) return "";
  if (calc.selection.method === "agent" && row.agent.available && row.agent.krw != null) return formatKrw(row.agent.krw);
  if (row.single.route === "hold") return HOLD_TEXT;
  const extra = calc.staged.enabled && calc.escalation.model_id ? calc.escalation.per_submission_krw : 0;
  return formatKrw(row.single.krw + extra, row.single.open_ended);
}

/** 「담는 크기」 — 한 번 호출에 담을 수 있는 글자 수 · 소스 파일 수. */
export function capacityText(calc: ScoringCalculator): string {
  const row = selectedRow(calc);
  if (!row) return "";
  return `${charsLabel(row.single.capacity_chars)} · 소스 파일 약 ${fileCount(row.single.capacity_files)}개`;
}
