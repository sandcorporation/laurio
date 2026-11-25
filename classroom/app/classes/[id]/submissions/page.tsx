"use client";

// 클래스 「제출」 화면(#1317) — 「최근 제출」 카드의 「전체」. 같은 줄 모양·최신순·쪽 넘김이고, 「채점 실패」 점수인
// (문제, 학생)의 최근 시도에만 「다시 채점」이 붙는다. 누르면 확인 창이 「예상 비용」 카드와 같은 셈의 금액을 보인다.
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { AccessNotice } from "@/app/components/AccessNotice";
import { Card, ErrorNote, PageHeader, PageShell, buttonClass } from "@/app/components/ui";
import { bffClient } from "@/lib/bff/client";
import {
  classAttemptVerdictsPath,
  requestRegrade,
  useClassAttempts,
  type ClassAttemptRow,
  type ClassAttemptVerdicts,
} from "@/lib/classes/use-class-attempts";
import type { ClassRow } from "@/lib/classes/api";
import { attemptWaitingNote } from "@/lib/classes/scoring-block-note";
import { MissingScoringKeyNote } from "@/app/components/MissingScoringKeyNote";
import { useClass } from "@/lib/classes/use-class";
import { useClassroomTabTitle } from "@/lib/rendering/use-tab-title";
import { calculatorPath, submissionAmount, type ScoringCalculator } from "@/lib/scoring/calculator";

import { SubmissionVerdictList } from "@/app/components/SubmissionVerdictList";
import { AttemptLine } from "../recent-attempts-card";

function RegradeDialog({
  classId,
  attempt,
  busy,
  failed,
  onCancel,
  onConfirm,
}: {
  classId: number;
  attempt: ClassAttemptRow;
  busy: boolean;
  failed: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  // 「예상 비용」 카드와 같은 셈 — 지금 이 클래스의 조합으로 그 문제의 제출 한 건.
  const { state } = useBackendQuery<ScoringCalculator>(bffClient, calculatorPath(classId, { problemId: attempt.problem_id }));
  const amount = state.status === "ready" ? submissionAmount(state.data) : state.status === "error" ? "—" : "…";
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-ink/40 p-4">
      <button type="button" aria-label="닫기" onClick={onCancel} className="fixed inset-0 cursor-default" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="다시 채점"
        data-testid="regrade-dialog"
        className="relative w-full max-w-[420px] border border-rule bg-surface p-5"
      >
        <h2 className="text-[16px] font-semibold">다시 채점할까요?</h2>
        <p className="mt-2 break-keep text-[13px] text-ink/70">
          {attempt.member_display_name} <span className="text-ink/45">·</span> {attempt.problem_title}
        </p>
        <p data-testid="regrade-amount" className="mt-1 text-[13px] text-ink/70">
          예상 금액 {amount}
        </p>
        {failed ? (
          <p data-testid="regrade-error" className="mt-2 text-[12.5px] text-error">
            다시 채점을 걸지 못했습니다.
          </p>
        ) : null}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" data-testid="regrade-cancel" onClick={onCancel} className={buttonClass("secondary", "sm")}>
            취소
          </button>
          <button
            type="button"
            data-testid="regrade-confirm"
            disabled={busy}
            onClick={onConfirm}
            className={buttonClass("primary", "sm")}
          >
            다시 채점
          </button>
        </div>
      </div>
    </div>
  );
}

// 펼친 줄의 판정(#1334) — 펼칠 때 그 제출 하나만 읽는다. 채점 전·실패면 판정 대신 빈 글자.
function AttemptVerdicts({
  classId,
  attempt,
  classroom,
}: {
  classId: number;
  attempt: ClassAttemptRow;
  classroom: ClassRow | null;
}) {
  const { state } = useBackendQuery<ClassAttemptVerdicts>(bffClient, classAttemptVerdictsPath(classId, attempt.id));
  const testId = `class-attempt-${attempt.id}`;
  if (state.status === "loading") {
    return (
      <p data-testid={`${testId}-verdicts-loading`} className="text-[12.5px] text-ink/45">
        불러오는 중...
      </p>
    );
  }
  if (state.status === "error") {
    return (
      <p data-testid={`${testId}-verdicts-error`} className="text-[12.5px] text-error">
        불러오지 못했습니다.
      </p>
    );
  }
  const { score, checklist_items: items } = state.data;
  const waiting = score === null ? attemptWaitingNote(attempt, classroom, classId) : null;
  if (waiting) {
    return (
      <MissingScoringKeyNote
        classId={classId}
        {...waiting}
        noteTestId={`${testId}-waiting-note`}
        settingsLinkTestId={`${testId}-waiting-link`}
      />
    );
  }
  if (score === null) {
    return (
      <p data-testid={`${testId}-verdicts-empty`} className="text-[12.5px] text-ink/45">
        —
      </p>
    );
  }
  return (
    <SubmissionVerdictList
      score={score}
      checklistLabelById={new Map(items.map((item) => [item.id, item.label]))}
      testIdPrefix={testId}
    />
  );
}

function ClassAttempts() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const page = Math.max(1, Number(useSearchParams().get("page")) || 1);
  const { state, reload } = useClassAttempts(classId, page);
  const { state: classState, reload: reloadClass } = useClass(classId);
  const [target, setTarget] = useState<ClassAttemptRow | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  useClassroomTabTitle({
    screenName: "제출",
    className: classState.status === "ready" ? classState.classroom.name : undefined,
  });

  function open(attempt: ClassAttemptRow) {
    setFailed(false);
    setTarget(attempt);
  }

  async function confirm() {
    if (!target) return;
    setBusy(true);
    const result = await requestRegrade(classId, target.id);
    setBusy(false);
    if (result.ok && result.data.corrections.length > 0) {
      setTarget(null);
      reload();
    } else {
      setFailed(true);
    }
  }

  const pageHref = (n: number) => `/classes/${classId}/submissions?page=${n}`;

  // 클래스를 먼저 본다 — 강사가 아니면 시도 목록의 404 는 오류가 아니라 접근 안내다(#1390).
  if (classState.status === "notFound") {
    return (
      <PageShell>
        <AccessNotice
          page="class"
          classId={classId}
          testId="class-attempts-not-found"
          retry={{
            reload: () => {
              reloadClass();
              reload();
            },
            turns: [classState],
          }}
        />
      </PageShell>
    );
  }

  return (
    <PageShell>
      <PageHeader
        eyebrow={classState.status === "ready" ? classState.classroom.name : undefined}
        title="제출"
        titleTestId="class-attempts-heading"
      />
      {classState.status === "loading" || state.status === "loading" ? (
        <p data-testid="class-attempts-loading" className="text-[13.5px] text-ink/45">
          불러오는 중...
        </p>
      ) : classState.status === "error" || state.status === "error" ? (
        <ErrorNote>
          <span data-testid="class-attempts-error">제출을 불러오지 못했습니다.</span>
        </ErrorNote>
      ) : (
        <>
          <Card>
            {state.data.rows.length === 0 ? (
              <p data-testid="class-attempts-empty" className="px-4 py-3 text-[12.5px] text-ink/45">
                —
              </p>
            ) : (
              <ol data-testid="class-attempts" className="divide-y divide-rule">
                {state.data.rows.map((attempt) => (
                  <AttemptLine
                    key={attempt.id}
                    attempt={attempt}
                    testId={`class-attempt-${attempt.id}`}
                    toggle={{
                      expanded: expandedId === attempt.id,
                      onToggle: () => setExpandedId(expandedId === attempt.id ? null : attempt.id),
                    }}
                    detail={<AttemptVerdicts
                        classId={classId}
                        attempt={attempt}
                        classroom={classState.status === "ready" ? classState.classroom : null}
                      />}
                    action={
                      attempt.correctable ? (
                        <button
                          type="button"
                          data-testid={`regrade-${attempt.id}`}
                          onClick={() => open(attempt)}
                          className={`${buttonClass("secondary", "sm")} shrink-0`}
                        >
                          다시 채점
                        </button>
                      ) : null
                    }
                  />
                ))}
              </ol>
            )}
          </Card>
          {page > 1 || state.data.has_next ? (
            <nav className="mt-4 flex justify-end gap-2">
              {page > 1 ? (
                <Link href={pageHref(page - 1)} data-testid="class-attempts-prev" className={buttonClass("secondary", "sm")}>
                  이전
                </Link>
              ) : null}
              {state.data.has_next ? (
                <Link href={pageHref(page + 1)} data-testid="class-attempts-next" className={buttonClass("secondary", "sm")}>
                  다음
                </Link>
              ) : null}
            </nav>
          ) : null}
        </>
      )}
      {target ? (
        <RegradeDialog
          classId={classId}
          attempt={target}
          busy={busy}
          failed={failed}
          onCancel={() => setTarget(null)}
          onConfirm={confirm}
        />
      ) : null}
    </PageShell>
  );
}

export default function ClassAttemptsPage() {
  // `useSearchParams` 는 정적 빌드에서 Suspense 경계 안에 있어야 한다.
  return (
    <Suspense>
      <ClassAttempts />
    </Suspense>
  );
}
