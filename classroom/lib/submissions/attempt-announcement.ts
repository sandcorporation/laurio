// 가장 최근 시도의 상태를 스크린리더에 알리는 한 줄(#1431). 폴링이 같은 상태를 다시 가져와도 문장이
// 같아 다시 읽히지 않고, 상태가 바뀔 때만(채점 대기 → 미통과 등) 문장이 바뀌어 한 번 읽힌다.
import { STAMP_LABEL, stampKind } from "../design/stamp";
import { withLate } from "../problems/due-dates";

import type { ClassroomSubmissionRow } from "./api";

type Attempt = Pick<
  ClassroomSubmissionRow,
  "attempt_number" | "status" | "passed" | "perfect" | "late" | "pending_reason"
>;

export function attemptAnnouncement(submissions: readonly Attempt[]): string {
  const latest = submissions.reduce<Attempt | null>(
    (best, current) => (best === null || current.attempt_number > best.attempt_number ? current : best),
    null,
  );
  if (latest === null) return "";
  let label: string;
  if (latest.status === "pending") {
    label = latest.pending_reason === "rejected" ? "반려" : latest.pending_reason ? "채점 대기" : "채점 중";
  } else {
    const kind = stampKind(latest.passed, latest.perfect);
    label = kind ? STAMP_LABEL[kind] : "미통과";
  }
  return `시도 ${latest.attempt_number} ${withLate(label, latest.late)}`;
}
