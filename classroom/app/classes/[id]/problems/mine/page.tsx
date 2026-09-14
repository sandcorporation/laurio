"use client";

// 참여자의 문제 목록 (#288, 스타일 #298) — 통과/미통과가 한눈에 보인다. 강사
// 전용 클래스 상세(app/classes/[id]/page.tsx)와는 다른 화면이다 — 참여자는 그
// 클래스가 아예 없는 것처럼 404를 받으므로, 참여자 표면은 여기와
// problems/[problemId]/submit 뿐이다.
//
// **이 클래스에서 불릴 이름을 이 화면 위쪽에서 인라인으로 바꾼다**(#372) —
// 따로 설정 화면을 두지 않는다, 가입할 때 한 번 정한 이름을 나중에 고칠
// 유일한 자리가 여기다. 내보내진 참여자·보관된 클래스는 편집 칸 자체를
// 내지 않는다 — 강사가 문제를 열지 못하게 하는 것과 같은 신호
// (`memberExpelled`·`archived`)를 그대로 쓴다.
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import {
  Badge,
  Card,
  EmptyState,
  ErrorNote,
  FieldLabel,
  INPUT_CLASS,
  PageHeader,
  PageShell,
  buttonClass,
} from "@/app/components/ui";
import { BackendError } from "@/lib/backend/client";
import { renameMyself } from "@/lib/submissions/api";
import { useMyProblems } from "@/lib/submissions/use-my-problems";

function MyDisplayNameCard({
  classId,
  displayName,
  onRenamed,
}: {
  classId: number;
  displayName: string;
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
    <Card className="mb-5">
      <div className="flex flex-col gap-2.5 p-4">
        {editing ? (
          <form onSubmit={handleSubmit} className="flex flex-col gap-2.5">
            <label htmlFor="my-display-name-input">
              <FieldLabel>이 클래스에서 불릴 이름</FieldLabel>
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <input
                id="my-display-name-input"
                data-testid="my-display-name-input"
                value={nameInput}
                onChange={(event) => setNameInput(event.target.value)}
                required
                maxLength={100}
                className={`${INPUT_CLASS} min-w-[200px] flex-1`}
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
            </div>
          </form>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-[13.5px]">
              이 클래스에서 <b data-testid="my-display-name" className="text-ink">{displayName}</b>
              (으)로 불립니다.
            </p>
            <button
              type="button"
              data-testid="my-display-name-edit"
              onClick={() => setEditing(true)}
              className={buttonClass("secondary", "sm")}
            >
              이름 바꾸기
            </button>
          </div>
        )}
        {error ? (
          <ErrorNote>
            <span data-testid="my-display-name-error">{error}</span>
          </ErrorNote>
        ) : null}
      </div>
    </Card>
  );
}

export default function MyProblemsPage() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const { state, reload } = useMyProblems(classId);

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

  const { problems, memberDisplayName, memberExpelled, archived } = state;
  const passed = problems.filter((p) => p.passed).length;

  return (
    <PageShell>
      <PageHeader
        eyebrow="클래스"
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
      />

      {/* 내보내진 참여자·보관된 클래스는 편집 칸을 아예 내지 않는다(#372 AC) —
          어차피 서버가 403으로 거절할 요청을 화면에서 미리 막는다. */}
      {memberExpelled || archived ? null : (
        <MyDisplayNameCard classId={classId} displayName={memberDisplayName} onRenamed={reload} />
      )}

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
