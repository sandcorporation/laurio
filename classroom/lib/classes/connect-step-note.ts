// 「시작하기」 1단계 — 연결은 소유자만 넣는다(#561). 버튼이 없는 공동 강사에게는 누가 넣는지만 말한다(#1436-1).
export function connectStepNote(role: "owner" | "co_instructor"): string | null {
  return role === "owner" ? null : "소유자만 넣을 수 있습니다";
}
