"use client";

// 「최근 제출」 카드(#633, 백엔드 #632) — 강사가 이 화면을 여는 이유의 대부분은 「누가 방금 냈나」다.
// 최근 10건, 새것부터. 칸 모양은 참여자별 현황 격자와 같은 낱말·같은 표식이고, 권장 기한 뒤의 시도는
// 목록·내 시도와 같은 꼴로 결과 낱말에 「· 늦음」이 붙는다(#774).
import { Card, CardHeader } from "@/app/components/ui";
import { formatRelativeTime } from "@/lib/classes/relative-time";
import { withLate } from "@/lib/problems/due-dates";
import { useRecentAttempts, type RecentAttemptStatus } from "@/lib/classes/use-recent-attempts";

const STATUS_LABEL: Record<RecentAttemptStatus, { label: string; className: string }> = {
  passed: { label: "통과", className: "text-verified" },
  attempted_not_passed: { label: "미통과", className: "text-ink/60" },
  scoring: { label: "채점 중", className: "text-ink/45" },
  needs_setup: { label: "설정 필요", className: "text-attention" },
};

function AttemptMark({ status }: { status: RecentAttemptStatus }) {
  const size = "h-[14px] w-[14px] shrink-0";
  if (status === "passed") return <span className={`${size} bg-verified`} />;
  if (status === "attempted_not_passed") return <span className={`${size} border border-attention`} />;
  if (status === "needs_setup") return <span className={`${size} border border-dashed border-attention`} />;
  return (
    <span
      className={`${size} border border-rule bg-[repeating-linear-gradient(45deg,var(--color-rule)_0_2px,transparent_2px_4px)]`}
    />
  );
}

export function RecentAttemptsCard({ classId }: { classId: number }) {
  const state = useRecentAttempts(classId);

  return (
    <Card>
      <CardHeader title="최근 제출" />
      {state.status === "loading" ? (
        <p data-testid="recent-attempts-loading" className="px-4 py-3 text-[12.5px] text-ink/45">
          불러오는 중...
        </p>
      ) : state.status === "error" ? (
        <p data-testid="recent-attempts-error" className="px-4 py-3 text-[12.5px] text-attention">
          불러오지 못했습니다.
        </p>
      ) : state.data.length === 0 ? (
        <p data-testid="recent-attempts-empty" className="px-4 py-3 text-[12.5px] text-ink/45">
          —
        </p>
      ) : (
        <ol data-testid="recent-attempts" className="divide-y divide-rule">
          {state.data.map((attempt) => {
            const status = STATUS_LABEL[attempt.status];
            return (
              <li key={attempt.id} data-testid={`recent-attempt-${attempt.id}`} className="flex items-center gap-2.5 px-4 py-2.5">
                <AttemptMark status={attempt.status} />
                <span className="min-w-0 flex-1 truncate text-[13px]">
                  {attempt.member_display_name} <span className="text-ink/45">·</span>{" "}
                  <span className="text-ink/60">{attempt.problem_title}</span>
                </span>
                <span className="shrink-0 whitespace-nowrap text-right">
                  <span className={`text-[12px] ${status.className}`}>{withLate(status.label, attempt.late)}</span>
                  <span className="block text-[11px] text-ink/30">{formatRelativeTime(attempt.submitted_at)}</span>
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}
