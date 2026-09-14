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
import { BackendError } from "@/lib/backend/client";
import { useClassroomTabTitle } from "@/lib/rendering/use-tab-title";
import { renameMyself } from "@/lib/submissions/api";
import { useMyProblems } from "@/lib/submissions/use-my-problems";

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
    setSaving(true);
    setError(null);
    try {
      await renameMyself(classId, nameInput.trim());
      setEditing(false);
      onRenamed();
    } catch (err) {
      setError(err instanceof BackendError ? err.message : "이름을 바꾸지 못했습니다.");
    } finally {
      setSaving(false);
    }
  }

  function cancel() {
    setNameInput(displayName);
    setError(null);
    setEditing(false);
  }

  return (
    <div className="flex flex-col items-end gap-1">
      {editing ? (
        <form onSubmit={handleSubmit} className="flex flex-wrap items-center justify-end gap-2">
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
        <span data-testid="my-display-name-error" className="text-[12px] text-attention">
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
        <p data-testid="my-problems-loading" className="text-[13.5px] text-ink/45">
          불러오는 중...
        </p>
      </PageShell>
    );
  }

  if (state.status === "notFound") {
    return (
      <PageShell>
        <h1 data-testid="my-problems-not-found" className="text-[22px] font-semibold">
          클래스를 찾을 수 없습니다
        </h1>
      </PageShell>
    );
  }

  if (state.status === "error") {
    return (
      <PageShell>
        <ErrorNote>
          <span data-testid="my-problems-error">문제 목록을 불러오지 못했습니다.</span>
        </ErrorNote>
      </PageShell>
    );
  }

  const { className, problems, memberDisplayName, memberExpelled, archived } = state;
  const passed = problems.filter((p) => p.passed).length;

  return (
    <PageShell>
      <PageHeader
        eyebrow={className}
        title="문제 목록"
        description={
          problems.length > 0 ? (
            <>
              {problems.length}개 중 <span className="font-mono text-ink">{passed}</span>개를
              통과했습니다. 한 번이라도 통과하면 계속 통과로 남으니, 남은 문제는 몇 번이든
              다시 내서 통과할 수 있습니다.
            </>
          ) : undefined
        }
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

      {problems.length === 0 ? (
        <Card>
          <EmptyState>
            <span data-testid="my-problems-empty-state">
              아직 열린 문제가 없습니다. 강사가 문제를 열면 여기에 나타납니다.
            </span>
          </EmptyState>
        </Card>
      ) : (
        <Card>
          <ul data-testid="my-problems-list" className="divide-y divide-rule">
            {problems.map((problem) => (
              <li
                key={problem.id}
                data-testid={`my-problem-row-${problem.id}`}
                className="flex items-center justify-between gap-4 px-4 py-3.5"
              >
                <Link
                  href={`/classes/${classId}/problems/${problem.id}/submit`}
                  data-testid={`my-problem-row-${problem.id}-link`}
                  className="min-w-0 text-[14px] hover:underline"
                >
                  {problem.title}
                </Link>
                <span data-testid={`my-problem-row-${problem.id}-status`} className="shrink-0">
                  <Badge tone={problem.passed ? "verified" : "neutral"}>
                    {problem.passed ? "통과" : "미통과"}
                  </Badge>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </PageShell>
  );
}
