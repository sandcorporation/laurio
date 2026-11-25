"use client";

// 「최근 제출」 카드(#633, 백엔드 #632) — 강사가 이 화면을 여는 이유의 대부분은 「누가 방금 냈나」다.
// 최근 10건, 새것부터. 칸 모양은 참여자별 현황 격자와 같은 낱말·같은 표식이고, 권장 기한 뒤의 시도는
// 목록·내 시도와 같은 꼴로 결과 낱말에 「· 늦음」이 붙는다(#774).
import type { ReactNode } from "react";

import Link from "next/link";

import { Card, CardHeader } from "@/app/components/ui";
import { formatRelativeTime } from "@/lib/classes/relative-time";
import { knownOr } from "@/lib/util/known-or";
import { withLate } from "@/lib/problems/due-dates";
import { useRecentAttempts, type RecentAttemptRow, type RecentAttemptStatus } from "@/lib/classes/use-recent-attempts";
import { SCORING_LABEL, WAITING_LABEL } from "@/lib/submissions/status-names";

const UNKNOWN_STATUS = { label: "확인 중", className: "text-ink/45" };

const STATUS_LABEL: Record<RecentAttemptStatus, { label: string; className: string }> = {
  passed: { label: "통과", className: "text-success" },
  attempted_not_passed: { label: "미통과", className: "text-ink/60" },
  scoring_failed: { label: "채점 실패", className: "text-ink/60" },
  scoring: { label: SCORING_LABEL, className: "text-ink/45" },
  needs_setup: { label: WAITING_LABEL, className: "text-warning" },
};

function AttemptMark({ status }: { status: RecentAttemptStatus }) {
  const size = "h-[14px] w-[14px] shrink-0";
  if (status === "passed") return <span className={`${size} bg-success`} />;
  if (status === "attempted_not_passed" || status === "scoring_failed") return <span className={`${size} border border-error`} />;
  if (status === "needs_setup") return <span className={`${size} border border-dashed border-warning`} />;
  return (
    <span
      className={`${size} border border-rule bg-[repeating-linear-gradient(45deg,var(--color-rule)_0_2px,transparent_2px_4px)]`}
    />
  );
}

/** 시도 한 줄 — 「최근 제출」 카드와 「제출」 화면(#1317)이 같이 쓴다. `action` 은 줄 끝에 붙는다(「다시 채점」).
 * `toggle` 을 주면 줄 본문이 펼침 단추가 되고(#1334), 펼쳤을 때 `detail` 이 줄 아래에 붙는다. */
export function AttemptLine({
  attempt,
  testId,
  action,
  toggle,
  detail,
}: {
  attempt: RecentAttemptRow;
  testId: string;
  action?: ReactNode;
  toggle?: { expanded: boolean; onToggle: () => void };
  detail?: ReactNode;
}) {
  const status = knownOr(STATUS_LABEL, attempt.status, UNKNOWN_STATUS);
  const body = (
    <>
      <AttemptMark status={attempt.status} />
      <span className="min-w-0 flex-1 truncate text-[13px]">
        {attempt.member_display_name} <span className="text-ink/45">·</span>{" "}
        <span className="text-ink/60">{attempt.problem_title}</span>
      </span>
      <span className="shrink-0 whitespace-nowrap text-right">
        <span className={`text-[12px] ${status.className}`}>{withLate(status.label, attempt.late)}</span>
        <span className="block text-[11px] text-ink/30">{formatRelativeTime(attempt.submitted_at)}</span>
      </span>
    </>
  );
  return (
    <li data-testid={testId}>
      <div className="flex items-center gap-2.5 px-4 py-2.5">
        {toggle ? (
          <button
            type="button"
            data-testid={`${testId}-toggle`}
            aria-expanded={toggle.expanded}
            onClick={toggle.onToggle}
            className="flex min-w-0 flex-1 items-center gap-2.5 text-left"
          >
            {body}
          </button>
        ) : (
          body
        )}
        {action}
      </div>
      {toggle?.expanded && detail ? <div className="border-t border-rule px-4 py-3">{detail}</div> : null}
    </li>
  );
}

export function RecentAttemptsCard({ classId }: { classId: number }) {
  const state = useRecentAttempts(classId);

  return (
    <Card>
      <CardHeader
        title="최근 제출"
        hint={
          <Link href={`/classes/${classId}/submissions`} data-testid="recent-attempts-all" className="underline-offset-2 hover:underline">
            전체
          </Link>
        }
      />
      {state.status === "loading" ? (
        <p data-testid="recent-attempts-loading" className="px-4 py-3 text-[12.5px] text-ink/45">
          불러오는 중...
        </p>
      ) : state.status === "error" ? (
        <p data-testid="recent-attempts-error" className="px-4 py-3 text-[12.5px] text-error">
          불러오지 못했습니다.
        </p>
      ) : state.data.length === 0 ? (
        <p data-testid="recent-attempts-empty" className="px-4 py-3 text-[12.5px] text-ink/45">
          아직 제출이 없습니다.
        </p>
      ) : (
        <ol data-testid="recent-attempts" className="divide-y divide-rule">
          {state.data.map((attempt) => (
            <AttemptLine key={attempt.id} attempt={attempt} testId={`recent-attempt-${attempt.id}`} />
          ))}
        </ol>
      )}
    </Card>
  );
}
