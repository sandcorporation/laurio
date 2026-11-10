"use client";

// 강사의 제출 현황 화면 (#291, ADR-0040). 강사가 참여자들의 시도를 훑어보고
// 소스를 내려받거나 저장소를 열고, AI 판정과 그 근거를 함께 본다. **이 화면을
// 여는 것 자체는 어디에도 기록되지 않는다** — 이 서비스의 다른 곳에서 소스를
// 펼칠 때 남는 열람 이력과 달리, 강사가 채점 결과만 보고 넘어가는 것이
// 정상적인 운영이라 "몇 번 봤다"가 신호가 아니라 잡음이 되기 때문이다
// (docs/adr/0040-classroom-does-not-record-reads.md).
import Link from "next/link";
import { commitUrl, shortSha } from "@codemit/bff-client/repository-url";
import { useParams } from "next/navigation";

import { useState } from "react";

import {
  Badge,
  Card,
  EmptyState,
  ErrorNote,
  Note,
  Num,
  PageHeader,
  PageShell,
  buttonClass,
} from "@/app/components/ui";
import { MissingScoringKeyNote } from "@/app/components/MissingScoringKeyNote";
import { QualityRankingCard } from "@/app/components/QualityRankingCard";
import { SubmissionVerdictList } from "@/app/components/SubmissionVerdictList";
import { detailTabHref } from "@/lib/classes/detail-tab";
import { formatRelativeTime } from "@/lib/classes/relative-time";
import { useClass } from "@/lib/classes/use-class";
import { useRosterGrid } from "@/lib/roster-grid/use-roster-grid";
import type { InstructorSubmissionRow } from "@/lib/submissions/api";
import {
  latestPerMember,
  participantAttempts,
  participantIdsOf,
  requiredSummary,
  submissionStats,
} from "@/lib/submissions/latest-attempts";
import { useProblem } from "@/lib/problems/use-problem";
import { useClassroomTabTitle } from "@/lib/rendering/use-tab-title";
import { useProblemSubmissions } from "@/lib/submissions/use-problem-submissions";
import { withLate } from "@/lib/problems/due-dates";
import { instructorEntryBadge } from "@/lib/submissions/contest-entry";

const STATUS_LABEL: Record<string, string> = { draft: "초안", open: "열림", hidden: "숨김" };

function StatBar({ stats }: { stats: ReturnType<typeof submissionStats> }) {
  const cells: { key: string; label: string; value: string; tone?: string }[] = [
    {
      key: "passed",
      label: "통과",
      value: `${stats.passed}/${stats.participants ?? "—"}`,
      tone: "text-verified",
    },
    { key: "attempts", label: "시도", value: String(stats.attempts) },
    { key: "scoring", label: "채점 중", value: String(stats.scoring) },
    { key: "waiting", label: "채점 대기", value: String(stats.waiting) },
  ];
  return (
    <div data-testid="submissions-stat-bar" className="grid grid-cols-4 border border-rule bg-surface sm:flex sm:w-fit">
      {cells.map((cell) => (
        <div
          key={cell.key}
          data-testid={`submissions-stat-${cell.key}`}
          className="flex min-w-0 flex-col gap-0.5 border-r border-rule px-3 py-2.5 last:border-r-0 sm:min-w-[88px] sm:px-[18px]"
        >
          <span className="text-[11px] tracking-[0.06em] text-ink/45">{cell.label}</span>
          <Num className={`text-[16px] font-semibold ${cell.tone ?? ""}`}>{cell.value}</Num>
        </div>
      ))}
    </div>
  );
}

function StatusBadge({ submission }: { submission: InstructorSubmissionRow }) {
  if (submission.status === "pending") {
    return (
      <Badge tone={submission.pending_reason ? "attention" : "neutral"}>
        {withLate(submission.pending_reason ? "채점 대기" : "채점 중", submission.late)}
      </Badge>
    );
  }
  return (
    <Badge tone={submission.passed ? "verified" : "attention"}>
      {withLate(submission.passed ? "통과" : "미통과", submission.late)}
    </Badge>
  );
}

function AttemptRow({
  submission,
  items,
  syntaxCheckEnabled,
  checklistLabelById,
  open,
  onToggle,
}: {
  submission: InstructorSubmissionRow;
  items: { id: number; label: string; required: boolean }[];
  syntaxCheckEnabled: boolean;
  checklistLabelById: ReadonlyMap<number, string>;
  open: boolean;
  onToggle: () => void;
}) {
  const testId = `instructor-submission-row-${submission.id}`;
  const summary = requiredSummary(submission, items, syntaxCheckEnabled);
  const entry = instructorEntryBadge(submission);
  const canOpen = submission.status === "scored" && submission.score !== null;
  return (
    <li data-testid={testId} className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1.5">
        <span data-testid={`${testId}-member`} className="w-[90px] shrink-0 truncate text-[13.5px]">
          {submission.member_display_name}
        </span>
        <span data-testid={`${testId}-attempt`} className="w-[44px] shrink-0 text-[12px] text-ink/45">
          <Num>시도 {submission.attempt_number}</Num>
        </span>
        <span data-testid={`${testId}-status`}>
          <StatusBadge submission={submission} />
        </span>
        {entry ? (
          <span data-testid={`${testId}-contest-entry`}>
            <Badge tone={entry.tone}>{entry.label}</Badge>
          </span>
        ) : null}
        <span data-testid={`${testId}-required`} className="order-5 w-full basis-full text-[12.5px] text-ink/60 sm:order-none sm:w-auto sm:min-w-0 sm:flex-1 sm:basis-0">
          필수 {summary.met ?? "—"}/{summary.total}
          {summary.unmet.length > 0 ? ` — ${summary.unmet.join(", ")}` : ""}
        </span>
        <span className="order-4 ml-auto text-[11.5px] text-ink/45 sm:order-none sm:ml-0">{formatRelativeTime(submission.created_at)}</span>
        {canOpen ? (
          <button
            type="button"
            data-testid={`${testId}-verdict-toggle`}
            aria-expanded={open}
            onClick={onToggle}
            className="order-6 px-3 py-1.5 text-[12.5px] text-ink/60 underline underline-offset-[3px] hover:text-ink sm:order-none"
          >
            판정
          </button>
        ) : null}
        {submission.submission_format === "repository" ? (
          <>
            <a
              href={submission.value}
              target="_blank"
              rel="noreferrer"
              data-testid={`${testId}-repository`}
              className="order-6 px-3 py-1.5 text-[12.5px] text-ink/60 underline underline-offset-[3px] hover:text-ink sm:order-none"
            >
              저장소
            </a>
            {/* 고정 커밋(#777) — 브랜치·커밋으로 낸 시도만, 낸 주소 옆에 짧은 SHA 를 커밋 링크로. */}
            {submission.commit_sha ? (
              <a
                href={commitUrl(submission.value, submission.commit_sha)}
                target="_blank"
                rel="noreferrer"
                data-testid={`${testId}-commit`}
                className="order-6 py-1.5 font-mono text-[12px] text-ink/60 hover:text-ink sm:order-none"
              >
                {shortSha(submission.commit_sha)}
              </a>
            ) : null}
          </>
        ) : submission.download_url ? (
          <a
            href={submission.download_url}
            data-testid={`${testId}-download`}
            className="order-6 px-3 py-1.5 text-[12.5px] text-ink/60 underline underline-offset-[3px] hover:text-ink sm:order-none"
          >
            다운로드
          </a>
        ) : null}
      </div>
      {open && canOpen && submission.score ? (
        <div className="mt-3 border-t border-rule pt-3">
          <SubmissionVerdictList
            score={submission.score}
            checklistLabelById={checklistLabelById}
            testIdPrefix={testId}
          />
        </div>
      ) : null}
    </li>
  );
}

export default function ProblemSubmissionsPage() {
  const params = useParams<{ id: string; problemId: string }>();
  const classId = Number(params.id);
  const problemId = Number(params.problemId);

  const problemState = useProblem(classId, problemId);
  const { state } = useProblemSubmissions(classId, problemId);
  const { state: classState } = useClass(classId);
  const { state: gridState } = useRosterGrid(classId);
  const [showAll, setShowAll] = useState(false);
  const [openIds, setOpenIds] = useState<ReadonlySet<number>>(new Set());

  useClassroomTabTitle({
    screenName: "제출 현황",
    className: classState.status === "ready" ? classState.classroom.name : undefined,
    problemTitle: problemState.state.status === "ready" ? problemState.state.problem.title : undefined,
  });

  if (state.status === "loading" || problemState.state.status === "loading") {
    return (
      <PageShell>
        <p data-testid="problem-submissions-loading" className="text-[13.5px] text-ink/45">불러오는 중...</p>
      </PageShell>
    );
  }

  if (state.status === "notFound") {
    return (
      <PageShell>
        <h1 data-testid="problem-submissions-not-found" className="text-[22px] font-semibold">
          문제를 찾을 수 없습니다
        </h1>
      </PageShell>
    );
  }

  if (state.status === "error" || problemState.state.status === "error") {
    return (
      <PageShell>
        <ErrorNote>
          <span data-testid="problem-submissions-error">제출 현황을 불러오지 못했습니다.</span>
        </ErrorNote>
      </PageShell>
    );
  }

  const problem = problemState.state.status === "ready" ? problemState.state.problem : null;
  const items = problem?.checklist_items ?? [];
  const syntaxCheckEnabled = problem?.syntax_check_enabled ?? false;
  const checklistLabelById = new Map(items.map((item) => [item.id, item.label]));
  const problemTitle = problem?.title ?? "";
  const problemStatus = problem?.status ?? "";

  // 사람 집합은 참여자 격자에서 온다 — 강사 본인과 내보낸 사람은 뺀다(클래스 상세의 달성률과 같은 집합).
  // 격자를 아직 못 받았으면 목록은 그대로 두고 분모와 「안 낸 사람」만 비운다.
  const participantIds =
    gridState.status === "ready" ? participantIdsOf(gridState.grid) : null;
  const submissions = participantAttempts(state.submissions, participantIds);
  const stats = submissionStats(submissions, participantIds ? participantIds.size : null);
  const submittedMembers = new Set(submissions.map((s) => s.member_id));
  const notSubmitted = participantIds
    ? [...participantIds].filter((id) => !submittedMembers.has(id)).length
    : null;

  // 이 화면은 「학생이 아직 안 냈다」와 「냈는데 강사 본인의 키 문제로 멈췄다」를 헷갈리기
  // 가장 쉬운 자리다(#346) — 시도가 하나라도 그 사유로 멈춰 있으면 통계 바 아래에서 먼저
  // 알리고 설정으로 가는 길을 준다. 크레딧 소진·서버 연결 불가도 채점 키를 쓸 수 없는
  // 상태로 같은 사유("no_api_key")에 실린다(#629).
  const blockedByMissingKey = submissions.some((s) => s.pending_reason === "no_api_key");
  // 키는 멀쩡한데 이 문제의 채점 모델을 그 키로 못 쓰는 경우(#403) — 다음 행동이 다르다.
  // 경고는 한 곳에서 한 줄(#670) — 둘이 겹치면 CONTEXT.md 「채점 대기」의 순서대로 키만 말한다.
  const blockedByRejectedModel =
    !blockedByMissingKey && submissions.some((s) => s.pending_reason === "model_rejected");

  const rows = showAll ? submissions : latestPerMember(submissions);
  const toggle = (id: number) =>
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <PageShell>
      <PageHeader
        eyebrow={classState.status === "ready" ? classState.classroom.name : undefined}
        title={`${problemTitle} · 제출 현황`}
        titleTestId="problem-submissions-heading"
        actions={
          <>
            <span data-testid="problem-submissions-status-badge">
              <Badge tone={problemStatus === "open" ? "verified" : problemStatus === "hidden" ? "attention" : "neutral"}>
                {STATUS_LABEL[problemStatus] ?? problemStatus}
              </Badge>
            </span>
            <Link
              href={`/classes/${classId}/problems/${problemId}`}
              data-testid="back-to-problem-link"
              className={buttonClass()}
            >
              문제 편집
            </Link>
          </>
        }
      />

      <div className="flex flex-col gap-4">
        <StatBar stats={stats} />

        {blockedByMissingKey ? (
          <MissingScoringKeyNote
            classId={classId}
            message="이 클래스의 채점 키 문제로 일부 시도가 채점되지 않고 있습니다 — 클래스 설정에서 확인해주세요."
            noteTestId="submissions-no-api-key-note"
            settingsLinkTestId="submissions-no-api-key-settings-link"
          />
        ) : null}

        {blockedByRejectedModel ? (
          <MissingScoringKeyNote
            classId={classId}
            message="이 키로 쓸 수 없는 채점 모델입니다 — 채점 모델을 바꿔주세요."
            noteTestId="submissions-model-rejected-note"
            settingsLinkTestId="submissions-model-rejected-settings-link"
            actionLabel="채점 모델 바꾸기"
            settingsAnchor="scoring-model"
          />
        ) : null}

        <div role="group" aria-label="보기" className="flex items-center gap-2 text-[12.5px]">
          {(
            [
              { all: false, label: "참여자별 최신 시도", testId: "submissions-view-latest" },
              { all: true, label: "모든 시도", testId: "submissions-view-all" },
            ] as const
          ).map((view) => (
            <button
              key={view.testId}
              type="button"
              data-testid={view.testId}
              aria-pressed={showAll === view.all}
              onClick={() => setShowAll(view.all)}
              className={
                showAll === view.all
                  ? "bg-ink px-3 py-1.5 font-medium text-paper"
                  : "border border-rule bg-surface px-3 py-1.5 text-ink"
              }
            >
              {view.label}
            </button>
          ))}
          {showAll ? null : (
            <span data-testid="submissions-sort" className="ml-auto text-ink/60">
              정렬: 최근 제출순
            </span>
          )}
        </div>

        <Card>
          {rows.length === 0 ? (
            <EmptyState>
              <span data-testid="problem-submissions-empty-state">아직 낸 시도가 없습니다.</span>
            </EmptyState>
          ) : (
            <ol data-testid="problem-submissions-list" className="divide-y divide-rule">
              {rows.map((submission) => (
                <AttemptRow
                  key={submission.id}
                  submission={submission}
                  items={items}
                  syntaxCheckEnabled={syntaxCheckEnabled}
                  checklistLabelById={checklistLabelById}
                  open={openIds.has(submission.id)}
                  onToggle={() => toggle(submission.id)}
                />
              ))}
            </ol>
          )}
          {notSubmitted !== null && notSubmitted > 0 ? (
            <div
              data-testid="submissions-not-submitted"
              className="border-t border-rule px-4 py-2.5 text-[12.5px] text-ink/45"
            >
              아직 내지 않은 참여자 <Num>{notSubmitted}</Num>명 —{" "}
              <Link
                href={detailTabHref(classId, "participants")}
                data-testid="submissions-not-submitted-link"
                className="underline underline-offset-[3px] hover:text-ink"
              >
                참여자 탭에서 보기
              </Link>
            </div>
          ) : null}
        </Card>

        <QualityRankingCard
          classId={classId}
          problemId={problemId}
          canChangeKey={classState.status === "ready" && classState.classroom.role === "owner"}
        />
      </div>
    </PageShell>
  );
}
