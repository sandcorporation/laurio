"use client";

// 참여자의 문제 목록 (#288) — 통과/미통과가 한눈에 보인다. 강사 전용 클래스
// 상세(app/classes/[id]/page.tsx)와는 다른 화면이다 — 참여자는 그 클래스가
// 아예 없는 것처럼 404를 받으므로, 참여자 표면은 여기와
// problems/[problemId]/submit 뿐이다.
import Link from "next/link";
import { useParams } from "next/navigation";

import { useMyProblems } from "@/lib/submissions/use-my-problems";

export default function MyProblemsPage() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const { state } = useMyProblems(classId);

  if (state.status === "loading") {
    return (
      <main>
        <p data-testid="my-problems-loading">불러오는 중...</p>
      </main>
    );
  }

  if (state.status === "notFound") {
    return (
      <main>
        <h1 data-testid="my-problems-not-found">클래스를 찾을 수 없습니다</h1>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main>
        <p data-testid="my-problems-error">문제 목록을 불러오지 못했습니다.</p>
      </main>
    );
  }

  const { problems } = state;

  return (
    <main>
      <h1>문제 목록</h1>
      {problems.length === 0 ? (
        <p data-testid="my-problems-empty-state">아직 열린 문제가 없습니다.</p>
      ) : (
        <ul data-testid="my-problems-list">
          {problems.map((problem) => (
            <li key={problem.id} data-testid={`my-problem-row-${problem.id}`}>
              <Link
                href={`/classes/${classId}/problems/${problem.id}/submit`}
                data-testid={`my-problem-row-${problem.id}-link`}
              >
                {problem.title}
              </Link>{" "}
              ·{" "}
              <span data-testid={`my-problem-row-${problem.id}-status`}>
                {problem.passed ? "통과" : "미통과"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
