import type { ClassroomSubmissionRow } from "@/lib/submissions/api";

// 문제 머리 제목 옆의 통과하지 못한 상태 배지(#1381, #1395) — 문제 목록과 같은 낱말을 쓴다.
// 가장 나중 시도가 아직 판정 전이면(키·모델 사정으로 멈춘 시도 포함) 실패가 아니다.
export function unpassedBadge(
  submissions: ReadonlyArray<Pick<ClassroomSubmissionRow, "attempt_number" | "status" | "pending_reason">>,
): { label: string; tone: "neutral" | "error" } {
  if (submissions.length === 0) return { label: "미제출", tone: "neutral" };
  const latest = submissions.reduce((a, b) => (b.attempt_number > a.attempt_number ? b : a));
  if (latest.status === "pending" && latest.pending_reason !== "rejected") {
    return { label: latest.pending_reason ? "채점 대기" : "채점 중", tone: "neutral" };
  }
  return { label: "미통과", tone: "error" };
}
