import type { SubmitBlockedReason } from "./api";

type Reason = NonNullable<SubmitBlockedReason>;

// 낼 수 없던 이유가 풀릴 때 알릴 문구.
const RELEASED: Record<Reason, string> = {
  archived: "보관이 풀려 다시 제출할 수 있습니다.",
  expelled: "이 클래스에 다시 들어와 제출할 수 있습니다.",
  left: "이 클래스에 다시 들어와 제출할 수 있습니다.",
  hidden: "문제가 다시 열려 제출할 수 있습니다.",
};

// 사유 사이 전환 — 백엔드는 우선순위대로 하나만 돌려주니(보관 → 내보냄 → 숨김) 이전 사유가 풀렸다고
// 추론하지 않고 현재 사유로 알린다.
const NOW: Record<Reason, string> = {
  archived: "클래스가 보관돼 제출할 수 없습니다.",
  expelled: "클래스에서 내보내져 제출할 수 없습니다.",
  left: "클래스에서 나가 제출할 수 없습니다.",
  hidden: "문제가 숨겨져 제출할 수 없습니다.",
};

export type BlockedChange = {
  // 늘 떠 있는 status 자리에 넣을 문구(없으면 빈 문자열).
  note: string;
  // 초점이 사라진 자리(body)로 떨어졌을 때만 옮길 곳 — 다른 칸의 초점은 어느 쪽도 빼앗지 않는다.
  focus: "none" | "blocked-note" | "form";
};

export function blockedChange(before: SubmitBlockedReason, after: SubmitBlockedReason): BlockedChange {
  if (before === after) return { note: "", focus: "none" };
  if (before === null) return { note: "", focus: "blocked-note" };
  if (after === null) return { note: RELEASED[before], focus: "form" };
  return { note: NOW[after], focus: "blocked-note" };
}
