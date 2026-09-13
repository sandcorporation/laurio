"use client";

// 강사의 제출 현황 화면 (#291, ADR-0040). 강사가 참여자들의 시도를 훑어보고
// 소스를 내려받거나 저장소를 열고, AI 판정과 그 근거를 함께 본다. **이 화면을
// 여는 것 자체는 어디에도 기록되지 않는다** — 이 서비스의 다른 곳에서 소스를
// 펼칠 때 남는 열람 이력과 달리, 강사가 채점 결과만 보고 넘어가는 것이
// 정상적인 운영이라 "몇 번 봤다"가 신호가 아니라 잡음이 되기 때문이다
// (docs/adr/0040-classroom-does-not-record-reads.md).
import Link from "next/link";
import { useParams } from "next/navigation";

import {
  Badge,
  Card,
  EmptyState,
  ErrorNote,
  Note,
  Num,
  PageHeader,
  PageShell,
  buttonClass,
} from "@/app/components/ui";
import { MissingScoringKeyNote } from "@/app/components/MissingScoringKeyNote";
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
      <PageShell>
        <p data-testid="problem-submissions-loading" className="text-[13.5px] text-ink/45">불러오는 중...</p>
      </PageShell>
    );
  }

  if (state.status === "notFound") {
    return (
      <PageShell>
        <h1 data-testid="problem-submissions-not-found" className="text-[22px] font-semibold">
          문제를 찾을 수 없습니다
        </h1>
      </PageShell>
    );
  }

  if (state.status === "error" || problemState.state.status === "error") {
    return (
      <PageShell>
        <ErrorNote>
          <span data-testid="problem-submissions-error">제출 현황을 불러오지 못했습니다.</span>
        </ErrorNote>
      </PageShell>
    );
  }

  const checklistLabelById = new Map(
    problemState.state.status === "ready"
      ? problemState.state.problem.checklist_items.map((item) => [item.id, item.label])
      : [],
  );
  const problemTitle = problemState.state.status === "ready" ? problemState.state.problem.title : "";
  // 이 화면은 「학생이 아직 안 냈다」와 「냈는데 강사 본인이 키를 안 넣어
  // 멈췄다」를 헷갈리기 가장 쉬운 자리다(#346) — 시도가 하나라도 그 사유로
  // 멈춰 있으면 목록 위에서 먼저 알리고 설정으로 가는 길을 준다.
  const blockedByMissingKey = state.submissions.some(
    (submission) => submission.pending_reason === "no_api_key",
  );

  return (
    <PageShell>
      <PageHeader
        eyebrow="클래스 · 문제"
        title={`${problemTitle} · 제출 현황`}
        titleTestId="problem-submissions-heading"
        description="시도마다 소스나 저장소를 열어 AI 판정과 함께 볼 수 있습니다."
        actions={
          <Link
            href={`/classes/${classId}/problems/${problemId}`}
            data-testid="back-to-problem-link"
            className={buttonClass()}
          >
            문제 편집으로
          </Link>
        }
      />

      <div className="flex flex-col gap-4">
        {blockedByMissingKey ? (
          <MissingScoringKeyNote
            classId={classId}
            message="이 클래스에 채점 키가 없어 일부 시도가 채점되지 않고 있습니다."
            noteTestId="submissions-no-api-key-note"
            settingsLinkTestId="submissions-no-api-key-settings-link"
          />
        ) : null}

        {state.submissions.length === 0 ? (
          <Card>
            <EmptyState>
              <span data-testid="problem-submissions-empty-state">
                아직 낸 시도가 없습니다. 참여자가 제출하면 여기에 나타납니다.
              </span>
            </EmptyState>
          </Card>
        ) : (
          <Card>
            <ol data-testid="problem-submissions-list" className="divide-y divide-rule">
              {state.submissions.map((submission) => (
                <li
                  key={submission.id}
                  data-testid={`instructor-submission-row-${submission.id}`}
                  className="px-4 py-4"
                >
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                    <span
                      data-testid={`instructor-submission-row-${submission.id}-member`}
                      className="text-[14px] font-medium"
                    >
                      {submission.member_display_name}
                    </span>
                    <span
                      data-testid={`instructor-submission-row-${submission.id}-attempt`}
                      className="text-[12px] text-ink/45"
                    >
                      <Num>{submission.attempt_number}</Num>번째 시도
                    </span>

                    {submission.status === "pending" ? (
                      <span data-testid={`instructor-submission-row-${submission.id}-status`}>
                        <Badge tone={submission.pending_reason === "no_api_key" ? "attention" : "neutral"}>
                          {submission.pending_reason ? "채점 대기" : "채점 중"}
                        </Badge>
                      </span>
                    ) : (
                      <span data-testid={`instructor-submission-row-${submission.id}-status`}>
                        <Badge tone={submission.passed ? "verified" : "attention"}>
                          채점 완료 · {submission.passed ? "통과" : "미통과"}
                        </Badge>
                      </span>
                    )}

                    <span className="ml-auto shrink-0">
                      {submission.submission_format === "repository" ? (
                        <a
                          href={submission.value}
                          target="_blank"
                          rel="noreferrer"
                          data-testid={`instructor-submission-row-${submission.id}-repository`}
                          className={buttonClass("secondary", "sm")}
                        >
                          저장소 열기
                        </a>
                      ) : submission.download_url ? (
                        <a
                          href={submission.download_url}
                          data-testid={`instructor-submission-row-${submission.id}-download`}
                          className={buttonClass("secondary", "sm")}
                        >
                          소스 다운로드
                        </a>
                      ) : null}
                    </span>
                  </div>

                  {submission.status === "scored" && submission.score ? (
                    <ul
                      data-testid={`instructor-submission-row-${submission.id}-verdicts`}
                      className="mt-3 flex flex-col gap-2 border-t border-rule pt-3"
                    >
                      {submission.score.reasoning.map((verdict) => (
                        <li key={verdict.checklist_item_id} className="flex gap-2.5">
                          <span
                            aria-hidden
                            className={`mt-1 h-[13px] w-[13px] shrink-0 border ${
                              verdict.is_met ? "border-verified bg-verified" : "border-attention"
                            }`}
                          />
                          <span className="text-[13px] leading-relaxed">
                            <span className={verdict.is_met ? "" : "text-ink"}>
                              {checklistLabelById.get(verdict.checklist_item_id) ?? "항목"}
                            </span>{" "}
                            <span className="text-ink/45">— {verdict.is_met ? "충족" : "미충족"}</span>
                            <span className="block text-ink/60">{verdict.reasoning}</span>
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ol>
          </Card>
        )}

        <Note>
          이 화면을 열어 봐도 <b className="text-ink">그 사실은 어디에도 남지 않습니다.</b>
        </Note>
      </div>
    </PageShell>
  );
}
