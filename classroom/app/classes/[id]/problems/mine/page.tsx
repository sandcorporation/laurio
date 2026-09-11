"use client";

// 참여자의 문제 목록 (#288, 스타일 #298) — 통과/미통과가 한눈에 보인다. 강사
// 전용 클래스 상세(app/classes/[id]/page.tsx)와는 다른 화면이다 — 참여자는 그
// 클래스가 아예 없는 것처럼 404를 받으므로, 참여자 표면은 여기와
// problems/[problemId]/submit 뿐이다.
import Link from "next/link";
import { useParams } from "next/navigation";

import { Badge, Card, EmptyState, ErrorNote, PageHeader, PageShell } from "@/app/components/ui";
import { useMyProblems } from "@/lib/submissions/use-my-problems";

export default function MyProblemsPage() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const { state } = useMyProblems(classId);

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

  const { problems } = state;
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
