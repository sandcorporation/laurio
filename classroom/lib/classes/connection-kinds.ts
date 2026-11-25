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

/** 꺼진 벤더 선택지의 이유 — 그 벤더의 키가 없거나 거부되어 스위치가 넘어갈 수 없을 때. 고를 수 있으면 null. */
export function vendorUnavailableReason(vendorKey: { switchable: boolean } | null): string | null {
  if (vendorKey === null) return "키 없음";
  return vendorKey.switchable ? null : "키 거부됨";
}

/** 키 줄 단추의 접근성 이름 — 보이는 글자(넣기·바꾸기·닫기·지우기)를 그대로 포함하고 어느 키인지 앞에 붙인다. */
export function vendorKeyButtonName(keyLabel: string, action: string): string {
  return `${keyLabel} ${action}`;
}
