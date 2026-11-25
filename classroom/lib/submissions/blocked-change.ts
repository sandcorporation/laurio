import type { SubmitBlockedReason } from "./api";

type Reason = NonNullable<SubmitBlockedReason>;

// 낼 수 없던 이유가 풀릴 때 알릴 문구.
const RELEASED: Record<Reason, string> = {
  archived: "보관이 풀려 다시 제출할 수 있습니다.",
  expelled: "이 클래스에 다시 들어와 제출할 수 있습니다.",
  left: "이 클래스에 다시 들어와 제출할 수 있습니다.",
  hidden: "문제가 다시 열려 제출할 수 있습니다.",
};

// 한 이유가 풀렸지만 다른 이유가 아직 막을 때 — 새 안내(role=alert)가 이유를 말하니 여기서는 바뀐 것만 알린다.
const SWITCHED: Record<Reason, string> = {
  archived: "보관은 풀렸지만 아직 제출할 수 없습니다.",
  expelled: "다시 들어왔지만 아직 제출할 수 없습니다.",
  left: "다시 들어왔지만 아직 제출할 수 없습니다.",
  hidden: "문제는 다시 열렸지만 아직 제출할 수 없습니다.",
};

export type BlockedChange = {
  // 늘 떠 있는 status 자리에 넣을 문구(없으면 빈 문자열).
  note: string;
  // 초점이 body 로 떨어졌을 때 옮길 곳. always 는 폼이 보이던 중 처음 막힌 경우.
  focus: "none" | "blocked-note-always" | "blocked-note" | "form";
};

export function blockedChange(before: SubmitBlockedReason, after: SubmitBlockedReason): BlockedChange {
  if (before === after) return { note: "", focus: "none" };
  if (before === null) return { note: "", focus: "blocked-note-always" };
  if (after === null) return { note: RELEASED[before], focus: "form" };
  return { note: SWITCHED[before], focus: "blocked-note" };
}
