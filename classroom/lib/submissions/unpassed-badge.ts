// 문제 머리 제목 옆의 통과하지 못한 상태 배지(#1381) — 문제 목록과 같은 낱말을 쓴다.
export function unpassedBadge(attemptCount: number): { label: string; tone: "neutral" | "error" } {
  return attemptCount === 0 ? { label: "미제출", tone: "neutral" } : { label: "미통과", tone: "error" };
}
