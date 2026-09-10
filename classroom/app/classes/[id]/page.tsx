"use client";

// 클래스 상세 (#278/#282). 이름·만든 날짜에 이어 문제 목록을 순서대로
// 보여준다. 남의 클래스는 백엔드가 404를 주므로 그대로 "찾을 수 없다"로
// 보여준다(존재를 알려주지 않는다).
import Link from "next/link";
import { useParams } from "next/navigation";

import { useClass } from "@/lib/classes/use-class";
import { useProblems } from "@/lib/problems/use-problems";

const STATUS_LABEL: Record<string, string> = {
  draft: "초안",
  open: "열림",
};

export default function ClassDetailPage() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const { state: classState } = useClass(classId);
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
      <p>
        <Link href={`/classes/${classId}/settings`} data-testid="scoring-settings-link">
          채점 설정
        </Link>
      </p>

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
