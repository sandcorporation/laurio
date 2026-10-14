"use client";

// 참여자의 문제 목록 (#288, 스타일 #298) — 통과/미통과가 한눈에 보인다. 강사
// 전용 클래스 상세(app/classes/[id]/page.tsx)와는 다른 화면이다 — 참여자는 그
// 클래스가 아예 없는 것처럼 404를 받으므로, 참여자 표면은 여기와
// problems/[problemId]/submit 뿐이다.
//
// **이 클래스에서 불릴 이름을 이 화면 헤더 오른쪽에서 그 자리에서 바꾼다**(#372,
// 자리는 #372 후속) — 따로 설정 화면을 두지 않는다, 가입할 때 한 번 정한 이름을
// 나중에 고칠 유일한 자리가 여기다. 처음엔 목록 위의 카드였는데, 가끔 쓰는
// 설정이 이 화면의 주인공인 목록과 같은 무게로 서 있었다. 눈썹은 클래스 이름이다
// — 이름이 클래스마다 따로라는 사실은 어느 클래스인지가 옆에 있어야 뜻이 통한다.
// 내보내진 참여자·보관된 클래스는 이름만 보이고 「바꾸기」가 없다 — 강사가 문제를
// 열지 못하게 하는 것과 같은 신호(`memberExpelled`·`archived`)를 그대로 쓴다.
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import {
  Badge,
  Card,
  EmptyState,
  ErrorNote,
  INPUT_CLASS,
  PageHeader,
  PageShell,
  buttonClass,
} from "@/app/components/ui";
import { formatRelativeTime } from "@/lib/classes/relative-time";
import { checkDisplayNameForBannedWords } from "@/lib/members/display-name-check";
import { useClassroomTabTitle } from "@/lib/rendering/use-tab-title";
import { renameMyself, type ProblemListItem } from "@/lib/submissions/api";
import { useMyProblems } from "@/lib/submissions/use-my-problems";

const STATUS_BADGE: Record<
  ProblemListItem["status"],
  { label: string; tone: "neutral" | "attention" | "verified" }
> = {
  passed: { label: "통과", tone: "verified" },
  attempted_not_passed: { label: "미통과", tone: "attention" },
  scoring: { label: "채점 중", tone: "neutral" },
  needs_setup: { label: "채점 대기", tone: "attention" },
  not_submitted: { label: "미제출", tone: "neutral" },
};

// 한 줄 — 행 전체가 링크다(#639). 제목 · 「시도 k회 · 마지막 …」(시도가 없으면 비운다) · 배지 하나.
function ProblemListRow({
  classId,
  problem,
}: {
  classId: number;
  problem: ProblemListItem;
}) {
  const badge = STATUS_BADGE[problem.status];
  return (
    <li data-testid={`my-problem-row-${problem.id}`}>
      <Link
        href={`/classes/${classId}/problems/${problem.id}/submit`}
        data-testid={`my-problem-row-${problem.id}-link`}
        className="flex items-center gap-3.5 px-4 py-2.5 hover:bg-ink/[0.03]"
      >
        <span className="min-w-0 flex-1 truncate text-[14px]">
          {problem.title}
        </span>
        {problem.attempt_count > 0 ? (
          <span
            data-testid={`my-problem-row-${problem.id}-attempts`}
            className="shrink-0 text-[12px] whitespace-nowrap text-ink/45"
          >
            시도 {problem.attempt_count}회 · 마지막{" "}
            {formatRelativeTime(problem.last_attempted_at)}
          </span>
        ) : null}
        <span
          data-testid={`my-problem-row-${problem.id}-status`}
          className="shrink-0"
        >
          <Badge tone={badge.tone}>{badge.label}</Badge>
        </span>
      </Link>
    </li>
  );
}

// 목록 아래 접힌 「▸ 숨겨진 문제 N」 한 줄(#406, #639) — 강사가 숨겼지만 한 번이라도
// 낸 문제만 여기 있다. 해당 문제가 있을 때만 자리를 차지하고, 기본은 접힌 채다.
function HiddenProblemsSection({
  classId,
  hiddenProblems,
}: {
  classId: number;
  hiddenProblems: ProblemListItem[];
}) {
  const [expanded, setExpanded] = useState(false);

  if (hiddenProblems.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        data-testid="hidden-problems-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((prev) => !prev)}
        className="flex items-center gap-1.5 self-start text-[12.5px] text-ink/45 hover:text-ink"
      >
        <span aria-hidden="true">{expanded ? "▾" : "▸"}</span>
        숨겨진 문제 {hiddenProblems.length}
      </button>
      {expanded ? (
        <Card>
          <ul
            data-testid="hidden-problems-list"
            className="divide-y divide-rule"
          >
            {hiddenProblems.map((problem) => (
              <ProblemListRow
                key={problem.id}
                classId={classId}
                problem={problem}
              />
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}

// 머리 아래 진행 한 줄(#639) — 「n/m 통과」 · 막대 · 「채점 중 a · 채점 대기 c · 미제출 b」.
// 열린 문제만 센다.
function ProgressLine({ problems }: { problems: ProblemListItem[] }) {
  const passed = problems.filter((p) => p.status === "passed").length;
  const scoring = problems.filter((p) => p.status === "scoring").length;
  const waiting = problems.filter((p) => p.status === "needs_setup").length;
  const notSubmitted = problems.filter(
    (p) => p.status === "not_submitted",
  ).length;
  const rest = [
    scoring > 0 ? `채점 중 ${scoring}` : null,
    waiting > 0 ? `채점 대기 ${waiting}` : null,
    notSubmitted > 0 ? `미제출 ${notSubmitted}` : null,
  ].filter((part): part is string => part !== null);
  return (
    <div
      data-testid="my-problems-progress"
      className="flex flex-wrap items-center gap-x-3.5 gap-y-1.5"
    >
      <span
        data-testid="my-problems-progress-count"
        className="font-mono text-[15px] font-semibold"
      >
        {passed}/{problems.length} 통과
      </span>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={problems.length}
        aria-valuenow={passed}
        className="relative h-2 w-full max-w-[320px] border border-rule bg-paper"
      >
        <div
          className="absolute inset-y-0 left-0 bg-verified"
          style={{ width: `${(passed / problems.length) * 100}%` }}
        />
      </div>
      {rest.length > 0 ? (
        <span
          data-testid="my-problems-progress-rest"
          className="text-[12px] text-ink/45"
        >
          {rest.join(" · ")}
        </span>
      ) : null}
    </div>
  );
}

function MyDisplayName({
  classId,
  displayName,
  editable,
  onRenamed,
}: {
  classId: number;
  displayName: string;
  /** 내보내진 참여자·보관된 클래스면 거짓 — 이름은 보이되 「바꾸기」가 없다. */
  editable: boolean;
  onRenamed: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [nameInput, setNameInput] = useState(displayName);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 다시 불러온 이름(저장 직후 `onRenamed`가 부른 새로고침, 또는 다른 탭에서
  // 바꾼 값)으로 입력칸 초기값을 맞춘다 — 편집 중이 아닐 때만이다, 타이핑
  // 중간에 덮어쓰면 안 되므로.
  useEffect(() => {
    if (!editing) setNameInput(displayName);
  }, [displayName, editing]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedName = nameInput.trim();
    // 제출을 누르는 순간에만 검사한다 — 타이핑 중에는 부르지 않는다(spec
    // #474, #476). 서버가 진짜 문이고(#475) 이건 편의라, 여기서 걸러도
    // 걸러지지 않아도 서버가 같은 이유로 다시 거절한다.
    const bannedWordMessage = checkDisplayNameForBannedWords(trimmedName);
    if (bannedWordMessage) {
      setError(bannedWordMessage);
      return;
    }
    setSaving(true);
    setError(null);
    const result = await renameMyself(classId, trimmedName);
    if (result.ok) {
      setEditing(false);
      onRenamed();
    } else {
      setError(result.detail);
    }
    setSaving(false);
  }

  function cancel() {
    setNameInput(displayName);
    setError(null);
    setEditing(false);
  }

  return (
    <div className="flex flex-col items-end gap-1">
      {editing ? (
        <form
          onSubmit={handleSubmit}
          className="flex flex-wrap items-center justify-end gap-2"
        >
          <input
            id="my-display-name-input"
            data-testid="my-display-name-input"
            aria-label="이 클래스에서 불릴 이름"
            value={nameInput}
            onChange={(event) => setNameInput(event.target.value)}
            required
            maxLength={100}
            autoFocus
            className={`${INPUT_CLASS} w-[200px]`}
          />
          <button
            type="submit"
            data-testid="my-display-name-submit"
            disabled={saving || nameInput.trim() === ""}
            className={buttonClass("primary", "sm")}
          >
            {saving ? "저장하는 중..." : "저장"}
          </button>
          <button
            type="button"
            data-testid="my-display-name-cancel"
            onClick={cancel}
            disabled={saving}
            className={buttonClass("secondary", "sm")}
          >
            취소
          </button>
        </form>
      ) : (
        <p className="text-[13px] text-ink/60">
          내 이름{" "}
          <b data-testid="my-display-name" className="font-medium text-ink">
            {displayName}
          </b>
          {editable ? (
            <>
              <span aria-hidden="true"> · </span>
              <button
                type="button"
                data-testid="my-display-name-edit"
                onClick={() => setEditing(true)}
                className="text-ink/60 underline underline-offset-2 hover:text-ink"
              >
                바꾸기
              </button>
            </>
          ) : null}
        </p>
      )}
      {error ? (
        <span
          data-testid="my-display-name-error"
          className="text-[12px] text-attention"
        >
          {error}
        </span>
      ) : null}
    </div>
  );
}

export default function MyProblemsPage() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const { state, reload } = useMyProblems(classId);

  useClassroomTabTitle({
    screenName: "문제 목록",
    className: state.status === "ready" ? state.className : undefined,
  });

  if (state.status === "loading") {
    return (
      <PageShell>
        <p
          data-testid="my-problems-loading"
          className="text-[13.5px] text-ink/45"
        >
          불러오는 중...
        </p>
      </PageShell>
    );
  }

  if (state.status === "notFound") {
    return (
      <PageShell>
        <h1
          data-testid="my-problems-not-found"
          className="text-[22px] font-semibold"
        >
          클래스를 찾을 수 없습니다
        </h1>
      </PageShell>
    );
  }

  if (state.status === "error") {
    return (
      <PageShell>
        <ErrorNote>
          <span data-testid="my-problems-error">
            문제 목록을 불러오지 못했습니다.
          </span>
        </ErrorNote>
      </PageShell>
    );
  }

  const {
    className,
    instructorNames,
    problems,
    hiddenProblems,
    memberDisplayName,
    memberExpelled,
    archived,
  } = state;

  return (
    <PageShell>
      <PageHeader
        eyebrow={
          instructorNames.length > 0
            ? `${className} · ${instructorNames.join(", ")}`
            : className
        }
        title="문제"
        actions={
          // 내보내진 참여자·보관된 클래스는 이름만 보이고 「바꾸기」가 없다(#372 AC) —
          // 어차피 서버가 403으로 거절할 요청을 화면에서 미리 막는다.
          <MyDisplayName
            classId={classId}
            displayName={memberDisplayName}
            editable={!memberExpelled && !archived}
            onRenamed={reload}
          />
        }
      />

      <div className="flex flex-col gap-5">
        {problems.length > 0 ? <ProgressLine problems={problems} /> : null}

        {problems.length === 0 ? (
          <Card>
            <EmptyState>
              <span data-testid="my-problems-empty-state">
                열린 문제가 없습니다
              </span>
            </EmptyState>
          </Card>
        ) : (
          <Card>
            <ul data-testid="my-problems-list" className="divide-y divide-rule">
              {problems.map((problem) => (
                <ProblemListRow
                  key={problem.id}
                  classId={classId}
                  problem={problem}
                />
              ))}
            </ul>
          </Card>
        )}

        <HiddenProblemsSection
          classId={classId}
          hiddenProblems={hiddenProblems}
        />
      </div>
    </PageShell>
  );
}
