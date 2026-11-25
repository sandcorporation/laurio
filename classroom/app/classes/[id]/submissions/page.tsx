"use client";

// 클래스 「제출」 화면(#1317) — 「최근 제출」 카드의 「전체」. 같은 줄 모양·최신순·쪽 넘김이고, 「채점 실패」 점수인
// (문제, 학생)의 최근 시도에만 「다시 채점」이 붙는다. 누르면 확인 창이 「예상 비용」 카드와 같은 셈의 금액을 보인다.
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { useDialogFocus } from "@codemit/bff-client/dialog-focus";
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

type RegradeDialogProps = {
  attempt: ClassAttemptRow;
  busy: boolean;
  failed: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  /** 연 단추가 다른 탭의 갱신으로 사라진 채 닫힐 때 초점을 받을 곳. */
  fallbackFocus: () => HTMLElement | null;
};

// 금액이 정해진 뒤에야 창을 연다 — 창이 열리며 초점이 들어갈 때 낭독기가 읽는 설명에 「…」 대신 금액이 들어 있게(#1484 ⑥).
function RegradeDialog({ classId, ...props }: RegradeDialogProps & { classId: number }) {
  // 「예상 비용」 카드와 같은 셈 — 지금 이 클래스의 조합으로 그 문제의 제출 한 건.
  const { state } = useBackendQuery<ScoringCalculator>(bffClient, calculatorPath(classId, { problemId: props.attempt.problem_id }));
  if (state.status === "loading") return <RegradeLoading onCancel={props.onCancel} />;
  return <RegradeDialogBody {...props} amount={state.status === "ready" ? submissionAmount(state.data) : "—"} />;
}

// 금액을 기다리는 동안(#1496 ⑦) — 창은 아직 없지만 누른 사람은 취소할 수 있어야 한다. 낭독되는 상태와 「취소」 단추(터치),
// Escape(키보드)로 그만두면 응답이 와도 창은 열리지 않는다(이 컴포넌트가 사라지며 응답은 버려진다). 초점은 누른 단추에 그대로 있다.
function RegradeLoading({ onCancel }: { onCancel: () => void }) {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onCancel();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);
  return (
    <div
      role="status"
      data-testid="regrade-loading"
      className="fixed bottom-4 left-1/2 z-30 flex -translate-x-1/2 items-center gap-3 border border-rule bg-surface px-4 py-2 text-[13px]"
    >
      <span>예상 금액을 불러오는 중...</span>
      <button type="button" data-testid="regrade-loading-cancel" onClick={onCancel} className={buttonClass("secondary", "sm")}>
        취소
      </button>
    </div>
  );
}

function RegradeDialogBody({
  attempt,
  amount,
  busy,
  failed,
  onCancel,
  onConfirm,
  fallbackFocus,
}: RegradeDialogProps & { amount: string }) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const { descriptionId } = useDialogFocus(dialogRef, {
    onEscape: onCancel,
    initialFocus: cancelRef,
    fallbackFocus,
  });
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-ink/40 p-4">
      <button type="button" tabIndex={-1} aria-label="닫기" onClick={onCancel} className="fixed inset-0 cursor-default" />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="다시 채점"
        aria-describedby={descriptionId}
        data-testid="regrade-dialog"
        className="relative w-full max-w-[420px] border border-rule bg-surface p-5"
      >
        <h2 className="text-[16px] font-semibold">다시 채점할까요?</h2>
        <div id={descriptionId}>
          <p className="mt-2 break-keep text-[13px] text-ink/70">
            {attempt.member_display_name} <span className="text-ink/45">·</span> {attempt.problem_title}
          </p>
          <p data-testid="regrade-amount" className="mt-1 text-[13px] text-ink/70">
            예상 금액 {amount}
          </p>
        </div>
        {/* 늘 있는 알림 영역 — 실패가 뜬 뒤에 만들어진 영역은 낭독기가 읽지 않는다. */}
        <p role="status" data-testid="regrade-error" className={failed ? "mt-2 text-[12.5px] text-error" : "sr-only"}>
          {failed ? "다시 채점을 걸지 못했습니다." : ""}
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <button ref={cancelRef} type="button" data-testid="regrade-cancel" onClick={onCancel} className={buttonClass("secondary", "sm")}>
            취소
          </button>
          <button
            type="button"
            data-testid="regrade-confirm"
            aria-disabled={busy || undefined}
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
  const [startedNote, setStartedNote] = useState("");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  // 금액을 기다리는 동안에도 초점이 돌아갈 곳 — 로딩 단계부터 연 단추를 기억한다(#1503 ④).
  const regradeOpener = useRef<HTMLElement | null>(null);

  useClassroomTabTitle({
    screenName: "제출",
    className: classState.status === "ready" ? classState.classroom.name : undefined,
  });

  // 연 단추는 클릭의 currentTarget 이다 — document.activeElement 는 낭독기 활성화·일부 터치에서 body 라 복귀가 body 가 된다(#1509 ②).
  function open(attempt: ClassAttemptRow, opener: HTMLElement) {
    regradeOpener.current = opener;
    setFailed(false);
    setStartedNote("");
    setTarget(attempt);
  }

  // 그만둘 때 초점을 먼저 옮긴다 — 「취소」 단추가 사라지며 초점이 body 로 빠지지 않게. 연 단추가 없으면 제목.
  function cancelRegrade() {
    const back = regradeOpener.current;
    regradeOpener.current = null;
    (back?.isConnected ? back : titleRef.current)?.focus();
    setTarget(null);
  }

  async function confirm() {
    if (!target) return;
    setBusy(true);
    const result = await requestRegrade(classId, target.id);
    setBusy(false);
    if (result.ok && result.data.corrections.length > 0) {
      // 걸리면 「다시 채점」 단추가 재조회에서 사라진다 — 단추 대신 늘 남는 제목이 초점을 받는다(#1471 ④).
      titleRef.current?.focus();
      setStartedNote(`${target.member_display_name} · ${target.problem_title} 다시 채점을 시작했습니다.`);
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
      <p role="status" data-testid="regrade-started" className="sr-only">
        {startedNote}
      </p>
      <PageHeader
        eyebrow={classState.status === "ready" ? classState.classroom.name : undefined}
        title="제출"
        titleTestId="class-attempts-heading"
        titleRef={titleRef}
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
                          aria-label={`다시 채점 ${attempt.member_display_name} ${attempt.problem_title}`}
                          onClick={(event) => open(attempt, event.currentTarget)}
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
          onCancel={cancelRegrade}
          onConfirm={confirm}
          fallbackFocus={() => titleRef.current}
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
