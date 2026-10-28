// 채점 연결 종류 고르기의 선택지(#803) — 방침 개정 시행일 전에는 「Claude(Anthropic) 키」를 보이지 않는다.
// 판정은 백엔드가 한다(`anthropic_key_selectable`) — 화면이 날짜를 비교하지 않는다.
import type { ClassRow } from "./api";

export type ConnectionKind = ClassRow["scoring_connection_kind"];

export const CLAUDE_KEY_LABEL = "Claude(Anthropic) 키";

const ALL: { kind: ConnectionKind; label: string }[] = [
  { kind: "openai_key", label: "OpenAI 키" },
  { kind: "anthropic_key", label: CLAUDE_KEY_LABEL },
  { kind: "compatible_server", label: "호환 서버" },
];

export function connectionKindOptions(selectable: boolean): { kind: ConnectionKind; label: string }[] {
  return selectable ? ALL : ALL.filter((option) => option.kind !== "anthropic_key");
}

/** 처음 선택으로 보일 종류 — 선택지에 없는 종류(시행일 전에 이미 Claude 로 저장된 클래스)는 첫 선택지로. */
export function initialConnectionKind(current: ConnectionKind, selectable: boolean): ConnectionKind {
  return connectionKindOptions(selectable).some((option) => option.kind === current) ? current : "openai_key";
}
