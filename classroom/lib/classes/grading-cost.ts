// 채점 연결의 벤더 라벨과 에이전트를 고를 수 없는 까닭(#1037). 건당 비용은 예상표(#1270·#1304, `lib/scoring/calculator`)가 단가표 × 가정으로 셈한다.
import type { ClassRow } from "./api";

export type VendorLabel = "OpenAI" | "Claude";

/** 연결된 키의 벤더 — 호환 서버는 벤더를 보이지 않는다. */
export function vendorLabel(kind: ClassRow["scoring_connection_kind"]): VendorLabel | null {
  if (kind === "openai_key") return "OpenAI";
  if (kind === "anthropic_key") return "Claude";
  return null;
}

export const UNAVAILABLE_TOOLTIP: Record<"compatible_server", string> = {
  compatible_server: "호환 서버",
};

/** 지금 기본 모델로는 에이전트를 고를 수 없을 때의 툴팁(#1311) — OpenAI 는 gpt-5-mini 이상만 받는다. */
export const AGENT_MODEL_TOOLTIP = "gpt-5-mini 이상";
