// 채점 비용 예상표(#1270·#1304) — 셈은 백엔드(`classroom.scoring_calculator`)가 하고, 여기는 바꿔 본 가정을 경로로 옮기고
// 받은 값을 라벨로 바꾼다. 숫자를 따로 적지 않는다.
import type { components } from "@codemit/bff-client";

import { formatKrw, formatManCount } from "./cost";

export type ScoringCalculator = components["schemas"]["ScoringCalculatorOut"];
export type CalculatorSpread = components["schemas"]["ScoringCalculatorSpreadOut"];
export type CalculatorRow = components["schemas"]["ScoringCalculatorRowOut"];
export type CalculatorSingleCell = components["schemas"]["ScoringCalculatorSingleCellOut"];
export type CalculatorAgentCell = components["schemas"]["ScoringCalculatorAgentCellOut"];
export type CalculatorMethod = "single" | "agent";
export type CalculatorEscalation = components["schemas"]["ScoringCalculatorEscalationOut"];
export type CalculatorStaged = components["schemas"]["ScoringCalculatorStagedOut"];
export type CalculatorAgentLimits = components["schemas"]["ScoringCalculatorAgentLimitsOut"];

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

const FROM_LABEL: Record<string, string> = { assumed: "가정", problem: "문제", custom: "입력" };

/** 가정 값 옆의 작은 라벨 — 어디서 온 값인가. */
export function fromLabel(from: string): string {
  return FROM_LABEL[from] ?? from;
}

const SOURCE_LABEL: Record<string, string> = { median: "중앙", p90: "큰 쪽(p90)" };

export function sourceLabel(source: { key: string; chars: number; measured: boolean }): string {
  return `${source.measured ? "제출" : "가정"} ${SOURCE_LABEL[source.key] ?? source.key} · ${formatManCount(source.chars)} 자`;
}

export function formatUsdPerMillion(input: number, output: number): string {
  return `입력 $${input} · 출력 $${output} / 100만 토큰`;
}

function formatSeconds(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds * 10) / 10}초`;
  return `${Math.round(seconds / 6) / 10}분`;
}

/** 감당 크기 — 한 번 호출에 담을 수 있는 소스 글자 수. */
export function capacityLabel(chars: number): string {
  return `${formatManCount(chars)} 자`;
}

/** 한 번 호출 칸의 둘째 줄 — 감당 크기와 이 크기에서 무슨 일이 생기는가. */
export function singleNote(single: CalculatorSingleCell, staged: CalculatorStaged): string {
  if (single.route === "hold") return `담지 못함 — 보류(채점 안 함) · ${capacityNote(single)}`;
  if (single.route === "two_step") return `두 걸음 · 고른 파일 ${capacityLabel(staged.budget_chars)}까지 읽음`;
  return capacityNote(single);
}

function capacityNote(single: CalculatorSingleCell): string {
  return `감당 ${capacityLabel(single.capacity_chars)} · 소스 파일 약 ${fileCount(single.capacity_files)}개 · 한글 주석 많음 ${capacityLabel(single.capacity_chars_hangul)} · 약 ${fileCount(single.capacity_files_hangul)}개`;
}

/** 소스 파일 수 — 천 단위 쉼표. */
export function fileCount(files: number): string {
  return files.toLocaleString("ko-KR");
}

/** 파일 평균 글자 수 — 가정 줄에 값으로 보인다. */
export function perFileLabel(charsPerFile: number): string {
  return `파일 평균 ${charsPerFile.toLocaleString("ko-KR")}자`;
}

/** 에이전트 칸의 둘째 줄 — 실측이 있으면 중앙, 없으면 가정한 시간만. */
export function agentNote(agent: CalculatorAgentCell): string {
  const measured = agent.measured_krw;
  if (measured.median != null && measured.p90 != null) {
    const time = agent.measured_seconds.median != null ? ` · ${formatSeconds(agent.measured_seconds.median)}` : "";
    return `실측 중앙 ${formatKrw(measured.median)}${time} (${measured.sample_count}건)`;
  }
  return agent.seconds != null ? `${formatSeconds(agent.seconds)} 가정` : "";
}

export function singleTimeLabel(single: CalculatorSingleCell): string {
  return `${formatSeconds(single.seconds)} 가정`;
}

/** 「두 걸음」 줄 — staged 가 켜져 있을 때만. */
export function twoStepLine(staged: CalculatorStaged): string {
  return `${formatManCount(staged.threshold_chars)} 자 넘으면 두 걸음 — 고른 파일 ${formatManCount(staged.budget_chars)} 자까지 읽음`;
}

/** 에이전트가 소스를 통째로 싣지 않고 파일을 골라 읽는 상한 — 코드가 거는 숫자 그대로. */
export function agentLimitsLine(limits: CalculatorAgentLimits): string {
  const mb = (bytes: number) => `${Math.round(bytes / (1024 * 1024))}MB`;
  return [
    `zip ${mb(limits.max_zip_bytes)}`,
    `풀린 크기 ${mb(limits.max_extracted_bytes)}`,
    `파일 ${formatManCount(limits.max_zip_entries)} 개`,
    `시간 ${limits.attempt_seconds}초 × ${limits.attempts}회`,
    `한 건 $${limits.budget_usd}`,
  ].join(" · ");
}

/** 의심 재판정 줄(#1291) — 꺼졌으면 `null`(「끔」), 아니면 의심 한 건당 예상과 의심 비율(가정)·제출 한 건에 더해지는 값. */
export function escalationCost(
  escalation: CalculatorEscalation,
): { model: string; perSuspect: string; rate: string; perSubmission: string } | null {
  if (!escalation.model_id || !escalation.per_suspect) return null;
  return {
    model: escalation.model_id,
    perSuspect: `의심 한 건당 ${formatKrw(escalation.per_suspect.krw, escalation.per_suspect.open_ended)}`,
    rate: `${Math.round(escalation.suspect_rate * 1000) / 10}%`,
    perSubmission: `제출 한 건에 ${formatKrw(escalation.per_submission_krw)}`,
  };
}
