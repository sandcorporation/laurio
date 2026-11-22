// 채점 비용 계산기(#1270) — 셈은 백엔드(`classroom.scoring_calculator`)가 하고, 여기는 고른 값을 경로로 옮기고
// 받은 값을 라벨로 바꾼다. 숫자를 따로 적지 않는다.
import type { components } from "@codemit/bff-client";

import { formatKrw, formatManCount } from "./cost";

export type ScoringCalculator = components["schemas"]["ScoringCalculatorOut"];
export type CalculatorSpread = components["schemas"]["ScoringCalculatorSpreadOut"];
export type CalculatorMethod = "single" | "agent";

export const NO_MEASUREMENT = "실측 없음";

/** 고른 값 — 빈 칸은 백엔드가 지금 이 클래스의 조합으로 채운다. */
export type CalculatorChoice = {
  vendor?: string;
  method?: CalculatorMethod;
  model?: string;
  problemId?: number;
  source?: string;
};

export function calculatorPath(classId: number, choice: CalculatorChoice): string {
  const params = new URLSearchParams();
  if (choice.vendor) params.set("vendor", choice.vendor);
  if (choice.method) params.set("method", choice.method);
  if (choice.model) params.set("model", choice.model);
  if (choice.problemId !== undefined) params.set("problem_id", String(choice.problemId));
  if (choice.source) params.set("source", choice.source);
  const query = params.toString();
  return `/api/backend/classroom/classes/${classId}/scoring-calculator${query ? `?${query}` : ""}`;
}

/** 한 칸을 바꾼다 — 프로바이더를 바꾸면 모델을, 문제를 바꾸면 소스 크기를 비워 그 선택지의 처음 값으로 간다. */
export function changeChoice(
  current: CalculatorChoice,
  field: keyof CalculatorChoice,
  value: string | number,
): CalculatorChoice {
  if (field === "vendor") return { ...current, vendor: String(value), model: undefined };
  if (field === "problemId") return { ...current, problemId: Number(value), source: undefined };
  if (field === "method") return { ...current, method: value === "agent" ? "agent" : "single" };
  return { ...current, [field]: String(value) };
}

const VENDOR_LABEL: Record<string, string> = { openai: "OpenAI", anthropic: "Claude" };

export function providerLabel(vendor: string): string {
  return VENDOR_LABEL[vendor] ?? vendor;
}

/** 에이전트를 고를 수 없는 프로바이더에 다는 짧은 까닭 — 되는 연결에서 읽는다(지금은 「Claude 키만」). */
export function agentOnlyLabel(agentVendors: readonly string[]): string {
  return `${agentVendors.map(providerLabel).join("·")} 키만`;
}

/** 에이전트 「되는 연결」 칸 — 「Claude 키」. */
export function agentConnectionsLabel(agentVendors: readonly string[]): string {
  return `${agentVendors.map(providerLabel).join("·")} 키`;
}

const SOURCE_LABEL: Record<string, string> = {
  median: "제출 중앙",
  p90: "제출 p90",
  small: "작음",
  medium: "보통",
  large: "큼",
};

export function sourceLabel(source: { key: string; chars: number }): string {
  return `${SOURCE_LABEL[source.key] ?? source.key} · ${formatManCount(source.chars)} 자`;
}

export function formatUsdPerMillion(input: number, output: number): string {
  return `입력 $${input} · 출력 $${output} / 100만 토큰`;
}

export function spreadKrw(spread: CalculatorSpread): string {
  if (spread.median == null || spread.p90 == null) return NO_MEASUREMENT;
  return `중앙 ${formatKrw(spread.median)} · p90 ${formatKrw(spread.p90)}`;
}

export function spreadSeconds(spread: CalculatorSpread): string {
  if (spread.median == null || spread.p90 == null) return NO_MEASUREMENT;
  return `중앙 ${formatSeconds(spread.median)} · p90 ${formatSeconds(spread.p90)}`;
}

function formatSeconds(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}초`;
  return `${Math.round(seconds / 6) / 10}분`;
}

/** 고른 방식의 제출 한 건 예상. */
export function headline(calc: ScoringCalculator): string {
  if (calc.selection.method === "agent") return spreadKrw(calc.agent.krw);
  return formatKrw(calc.single.krw, calc.single.open_ended);
}
