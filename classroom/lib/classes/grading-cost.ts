// 채점 연결의 벤더 라벨과 에이전트를 고를 수 없는 까닭(#1037). 건당 비용은 예상표(#1270·#1304, `lib/scoring/calculator`)가 단가표 × 가정으로 셈한다.
import type { ClassRow } from "./api";

export type VendorLabel = "OpenAI" | "Claude";

/** 연결된 키의 벤더 — 호환 서버는 벤더를 보이지 않는다. */
export function vendorLabel(kind: ClassRow["scoring_connection_kind"]): VendorLabel | null {
  if (kind === "openai_key") return "OpenAI";
  if (kind === "anthropic_key") return "Claude";
  return null;
}

/** 연결(키) 쪽 까닭 — 호환 서버는 에이전트를 돌리지 못한다. */
export const AGENT_KEY_NOTE: Record<"compatible_server", string> = {
  compatible_server: "호환 서버 연결에서는 에이전트를 쓸 수 없습니다.",
};

/** 모델 쪽 까닭(#1311) — 연결은 되는데 기본 모델이 에이전트를 받지 못한다. OpenAI 는 gpt-5-mini 이상만 받는다. */
export const AGENT_MODEL_NOTE = "기본 모델이 gpt-5-mini 이상이어야 에이전트를 고를 수 있습니다.";

export type AgentBlockedNote = { kind: "key" | "model"; text: string };

/** 에이전트가 꺼진 까닭을 글로 — 키(연결) 까닭이 앞서고, 둘 다 아니면 null. 단추 title 이 아니라 보이는 글과 `aria-describedby` 로 쓴다. */
export function agentBlockedNote({
  keyReason,
  modelBlocked,
}: {
  keyReason: "compatible_server" | null | undefined;
  modelBlocked: boolean;
}): AgentBlockedNote | null {
  if (keyReason) return { kind: "key", text: AGENT_KEY_NOTE[keyReason] };
  if (modelBlocked) return { kind: "model", text: AGENT_MODEL_NOTE };
  return null;
}
