"use client";

// 클래스 상세 (#278/#279/#282). 이름·만든 날짜에 이어 가입 링크, 그리고
// 문제 목록을 순서대로 보여준다. 남의 클래스는 백엔드가 404를 주므로 그대로
// "찾을 수 없다"로 보여준다(존재를 알려주지 않는다).
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { useClass } from "@/lib/classes/use-class";
import { useProblems } from "@/lib/problems/use-problems";

const STATUS_LABEL: Record<string, string> = {
  draft: "초안",
  open: "열림",
};

function joinLinkUrl(joinCode: string): string {
  if (typeof window === "undefined") return "";
  return `${window.location.origin}/join/${joinCode}`;
}

function JoinLinkSection({
  joinCode,
  regenerateError,
  onRegenerate,
}: {
  joinCode: string;
  regenerateError: boolean;
  onRegenerate: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const url = joinLinkUrl(joinCode);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <section>
      <h2>가입 링크</h2>
      <p data-testid="join-link">{url}</p>
      <button type="button" data-testid="join-link-copy" onClick={copy}>
        복사
      </button>
      {copied ? <span data-testid="join-link-copied"> 복사됨</span> : null}
      <p>
        <button type="button" data-testid="join-link-regenerate" onClick={onRegenerate}>
          다시 뽑기
        </button>
      </p>
      <p>다시 뽑으면 이전 링크는 더 이상 이 클래스로 들어오지 못합니다.</p>
      {regenerateError ? (
        <p data-testid="join-link-regenerate-error">다시 뽑지 못했습니다. 다시 시도해주세요.</p>
      ) : null}
    </section>
  );
}

export default function ClassDetailPage() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const { state: classState, regenerateJoinCode } = useClass(classId);
  const { state: problemsState, move } = useProblems(classId);

  if (classState.status === "loading") {
    return (
      <main>
        <p data-testid="classroom-detail-loading">불러오는 중...</p>
      </main>
    );
  }

  if (classState.status === "notFound") {
    return (
      <main>
        <h1 data-testid="classroom-detail-not-found">클래스를 찾을 수 없습니다</h1>
      </main>
    );
  }

  if (classState.status === "error") {
    return (
      <main>
        <p data-testid="classroom-detail-error">클래스 정보를 불러오지 못했습니다.</p>
      </main>
    );
  }

  return (
    <main>
      <h1 data-testid="classroom-detail-heading">{classState.classroom.name}</h1>
      <p data-testid="classroom-detail-created-at">
        {new Date(classState.classroom.created_at).toLocaleDateString("ko-KR")} 만듦
      </p>

      <JoinLinkSection
        joinCode={classState.classroom.join_code}
        regenerateError={classState.regenerateError}
        onRegenerate={regenerateJoinCode}
      />

      <h2>문제</h2>
      <p>
        <Link href={`/classes/${classId}/problems/new`} data-testid="new-problem-link">
          새 문제
        </Link>
      </p>

      {problemsState.status === "loading" ? (
        <p data-testid="problems-loading">불러오는 중...</p>
      ) : problemsState.status === "error" ? (
        <p data-testid="problems-error">문제 목록을 불러오지 못했습니다.</p>
      ) : problemsState.problems.length === 0 ? (
        <p data-testid="problems-empty-state">아직 만든 문제가 없습니다.</p>
      ) : (
        <>
          {problemsState.reorderError ? (
            <p data-testid="problems-reorder-error">순서를 바꾸지 못했습니다. 다시 시도해주세요.</p>
          ) : null}
          <ol data-testid="problems-list">
            {problemsState.problems.map((problem, index) => (
              <li key={problem.id} data-testid={`problem-row-${problem.id}`}>
                <Link
                  href={`/classes/${classId}/problems/${problem.id}`}
                  data-testid={`problem-row-${problem.id}-link`}
                >
                  {problem.title}
                </Link>
                <span data-testid={`problem-row-${problem.id}-status`}> · {STATUS_LABEL[problem.status]}</span>
                <button
                  type="button"
                  data-testid={`problem-row-${problem.id}-move-up`}
                  disabled={index === 0}
                  onClick={() => move(problem.id, "up")}
                >
                  위로
                </button>
                <button
                  type="button"
                  data-testid={`problem-row-${problem.id}-move-down`}
                  disabled={index === problemsState.problems.length - 1}
                  onClick={() => move(problem.id, "down")}
                >
                  아래로
                </button>
              </li>
            ))}
          </ol>
        </>
      )}
    </main>
  );
}
