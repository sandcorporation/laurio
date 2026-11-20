// 채점·완성도 검사 방식별 제출 한 건당 어림 비용(#1037). 실측한 숫자만 둔다 — 표에 없는 조합·모델은 「측정 없음」.
import type { ClassRow, GradingMethod } from "./api";

export const NO_MEASUREMENT = "측정 없음";

type CostEntry = { method: GradingMethod; model: string; perSubmission: string };

// 출처는 이슈 #1037 의 표다.
const COST_TABLE: readonly CostEntry[] = [
  // 공모전 3 제출 870 실측(입력 55K)
  { method: "single", model: "gpt-4o-mini", perSubmission: "약 $0.01" },
  // 제출 870·811 실측(입력 56K·309K)
  { method: "single", model: "gpt-4.1-mini", perSubmission: "$0.03~0.13" },
  // 7건 합 $0.74(c3-agent)
  { method: "agent", model: "claude-sonnet-5-5", perSubmission: "$0.07~0.17" },
  // 7건 합 $0.13(c3-agent)
  { method: "agent", model: "claude-haiku-5-5", perSubmission: "$0.01~0.03" },
];

export function perSubmissionCost(method: GradingMethod, model: string): string {
  return COST_TABLE.find((entry) => entry.method === method && entry.model === model)?.perSubmission ?? NO_MEASUREMENT;
}

export type VendorLabel = "OpenAI" | "Claude";

/** 연결된 키의 벤더 — 호환 서버는 벤더를 보이지 않는다. */
export function vendorLabel(kind: ClassRow["scoring_connection_kind"]): VendorLabel | null {
  if (kind === "openai_key") return "OpenAI";
  if (kind === "anthropic_key") return "Claude";
  return null;
}

export const UNAVAILABLE_TOOLTIP: Record<"compatible_server" | "agent_vendor_unverified", string> = {
  compatible_server: "호환 서버",
  agent_vendor_unverified: "OpenAI 키는 확인 전",
};
