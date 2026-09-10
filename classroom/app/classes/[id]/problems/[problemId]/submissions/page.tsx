"use client";

// 강사의 제출 현황 화면 (#291, ADR-0040). 강사가 참여자들의 시도를 훑어보고
// 소스를 내려받거나 저장소를 열고, AI 판정과 그 근거를 함께 본다. **이 화면을
// 여는 것 자체는 어디에도 기록되지 않는다** — Assignment의 출제자가 소스를
// 펼칠 때 남는 열람 이력과 달리, 강사가 채점 결과만 보고 넘어가는 것이
// 정상적인 운영이라 "몇 번 봤다"가 신호가 아니라 잡음이 되기 때문이다
// (docs/adr/0040-classroom-does-not-record-reads.md).
import Link from "next/link";
import { useParams } from "next/navigation";

import { useProblem } from "@/lib/problems/use-problem";
import { useProblemSubmissions } from "@/lib/submissions/use-problem-submissions";

export default function ProblemSubmissionsPage() {
  const params = useParams<{ id: string; problemId: string }>();
  const classId = Number(params.id);
  const problemId = Number(params.problemId);

  const problemState = useProblem(classId, problemId);
  const { state } = useProblemSubmissions(classId, problemId);

  if (state.status === "loading" || problemState.state.status === "loading") {
    return (
      <main>
        <p data-testid="problem-submissions-loading">불러오는 중...</p>
      </main>
    );
  }

  if (state.status === "notFound") {
    return (
      <main>
        <h1 data-testid="problem-submissions-not-found">문제를 찾을 수 없습니다</h1>
      </main>
    );
  }

  if (state.status === "error" || problemState.state.status === "error") {
    return (
      <main>
        <p data-testid="problem-submissions-error">제출 현황을 불러오지 못했습니다.</p>
      </main>
    );
  }

  const checklistLabelById = new Map(
    problemState.state.status === "ready"
      ? problemState.state.problem.checklist_items.map((item) => [item.id, item.label])
      : [],
  );
  const problemTitle = problemState.state.status === "ready" ? problemState.state.problem.title : "";

  return (
    <main>
      <h1 data-testid="problem-submissions-heading">{problemTitle} · 제출 현황</h1>
      <Link href={`/classes/${classId}/problems/${problemId}`} data-testid="back-to-problem-link">
        문제 편집으로
      </Link>

      {state.submissions.length === 0 ? (
        <p data-testid="problem-submissions-empty-state">아직 낸 시도가 없습니다.</p>
      ) : (
        <ol data-testid="problem-submissions-list">
          {state.submissions.map((submission) => (
            <li key={submission.id} data-testid={`instructor-submission-row-${submission.id}`}>
              <span data-testid={`instructor-submission-row-${submission.id}-member`}>
                {submission.member_display_name}
              </span>{" "}
              ·{" "}
              <span data-testid={`instructor-submission-row-${submission.id}-attempt`}>
                {submission.attempt_number}번째 시도
              </span>{" "}
              ·{" "}
              {submission.submission_format === "repository" ? (
                <a
                  href={submission.value}
                  target="_blank"
                  rel="noreferrer"
                  data-testid={`instructor-submission-row-${submission.id}-repository`}
                >
                  저장소 열기
                </a>
              ) : submission.download_url ? (
                <a
                  href={submission.download_url}
                  data-testid={`instructor-submission-row-${submission.id}-download`}
                >
                  소스 다운로드
                </a>
              ) : null}{" "}
              ·{" "}
              {submission.status === "pending" ? (
                <span data-testid={`instructor-submission-row-${submission.id}-status`}>채점 중</span>
              ) : (
                <span data-testid={`instructor-submission-row-${submission.id}-status`}>
                  채점 완료 · {submission.passed ? "통과" : "미통과"}
                </span>
              )}
              {submission.status === "scored" && submission.score ? (
                <ul data-testid={`instructor-submission-row-${submission.id}-verdicts`}>
                  {submission.score.reasoning.map((verdict) => (
                    <li key={verdict.checklist_item_id}>
                      {checklistLabelById.get(verdict.checklist_item_id) ?? "항목"} —{" "}
                      {verdict.is_met ? "충족" : "미충족"}
                      {": "}
                      {verdict.reasoning}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </main>
  );
}
