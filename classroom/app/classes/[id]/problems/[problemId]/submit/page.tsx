"use client";

// 참여자 제출 화면 (#286). 소스 또는 저장소를 내고, 낼 때마다 새 시도가
// 시도 목록에 쌓인다 — 마감도 횟수 상한도 없다(CONTEXT.md 「Problem」).
// 강사 전용 편집 화면(app/classes/[id]/problems/[problemId]/page.tsx)과는
// 다른 라우트다 — 참여자는 문제를 고치지 않고 그 정의를 읽고 낸다.
import { useParams } from "next/navigation";
import { useState } from "react";
import type { ChangeEvent, FormEvent } from "react";

import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  ErrorNote,
  FieldLabel,
  INPUT_CLASS,
  Note,
  Num,
  PageHeader,
  PageShell,
  buttonClass,
} from "@/app/components/ui";
import { ProblemDescription } from "@/app/components/ProblemDescription";
import { BackendError } from "@/lib/backend/client";
import { useMe } from "@/lib/auth/use-me";
import { submitAttempt } from "@/lib/submissions/api";
import { useMyProblem } from "@/lib/submissions/use-my-problem";
import { useSourceUpload } from "@/lib/submissions/use-source-upload";

function sourceTargetRef(problemId: number, userId: number): string {
  return `classroom-submission:${problemId}:${userId}:source`;
}

export default function ProblemSubmitPage() {
  const params = useParams<{ id: string; problemId: string }>();
  const classId = Number(params.id);
  const problemId = Number(params.problemId);
  const { state, reload } = useMyProblem(classId, problemId);
  const me = useMe();

  const [repositoryUrl, setRepositoryUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const targetRef =
    me.status === "ready" ? sourceTargetRef(problemId, me.userId) : null;
  const { state: uploadState, upload } = useSourceUpload(targetRef);

  if (state.status === "loading") {
    return (
      <PageShell>
        <p data-testid="my-problem-loading" className="text-[13.5px] text-ink/45">불러오는 중...</p>
      </PageShell>
    );
  }

  if (state.status === "notFound") {
    return (
      <PageShell>
        <h1 data-testid="my-problem-not-found" className="text-[22px] font-semibold">
          문제를 찾을 수 없습니다
        </h1>
      </PageShell>
    );
  }

  if (state.status === "error") {
    return (
      <PageShell>
        <ErrorNote>
          <span data-testid="my-problem-error">문제 정보를 불러오지 못했습니다.</span>
        </ErrorNote>
      </PageShell>
    );
  }

  const { problem, submissions } = state.data;

  async function submitValue(value: string, contentType?: string | null) {
    setSubmitting(true);
    setSubmitError(null);
    try {
      await submitAttempt(classId, problemId, { value, content_type: contentType });
      setRepositoryUrl("");
      reload();
    } catch (err) {
      setSubmitError(err instanceof BackendError ? err.message : "제출하지 못했습니다.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRepositorySubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await submitValue(repositoryUrl.trim());
  }

  async function handleSourceFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const uploaded = await upload(file);
      await submitValue(uploaded.objectKey, uploaded.contentType);
    } catch {
      // useSourceUpload가 이미 uploadState.error에 이유를 남긴다.
    }
  }

  const checklistLabelById = new Map(problem.checklist_items.map((item) => [item.id, item.label]));
  const requiredCount = problem.checklist_items.filter((item) => item.required).length;

  return (
    <PageShell>
      <PageHeader
        eyebrow="강의실 · 문제"
        title={problem.title}
        titleTestId="my-problem-title"
        actions={
          <span data-testid="my-problem-passed-status">
            <Badge tone={problem.passed ? "verified" : "neutral"}>
              {problem.passed ? "이 문제를 통과했습니다" : "아직 통과하지 못했습니다"}
            </Badge>
          </span>
        }
      />

      <div className="flex flex-col gap-5 lg:flex-row lg:items-start">
        <div className="flex min-w-0 flex-1 flex-col gap-5">
          {problem.description.trim() === "" ? null : (
            <Card>
              <CardHeader title="설명" />
              <div className="p-4" data-testid="my-problem-description">
                <ProblemDescription markdown={problem.description} />
              </div>
            </Card>
          )}

          <Card>
            <CardHeader title="체크리스트" hint={`필수 ${requiredCount}개를 전부 충족하면 통과`} />
            <ul data-testid="my-problem-checklist" className="divide-y divide-rule">
              {problem.checklist_items.map((item) => (
                <li
                  key={item.id}
                  data-testid={`checklist-item-${item.id}`}
                  className="flex items-start gap-3 px-4 py-3 text-[13.5px] leading-relaxed"
                >
                  <span className="flex-1">{item.label}</span>
                  <span className="shrink-0">
                    <Badge tone={item.required ? "attention" : "neutral"}>
                      {item.required ? "필수" : "선택"}
                    </Badge>
                  </span>
                </li>
              ))}
            </ul>
          </Card>

          <Card>
            <CardHeader title="내 시도" hint={submissions.length > 0 ? `${submissions.length}회` : undefined} />
            {submissions.length === 0 ? (
              <EmptyState>
                <span data-testid="submissions-empty-state">아직 낸 시도가 없습니다.</span>
              </EmptyState>
            ) : (
              <ol data-testid="submissions-list" className="divide-y divide-rule">
                {submissions.map((submission) => (
                  <li key={submission.id} data-testid={`submission-row-${submission.id}`} className="px-4 py-4">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                      <span
                        data-testid={`submission-row-${submission.id}-attempt`}
                        className="font-mono text-[12.5px] text-ink/45"
                      >
                        시도 {submission.attempt_number}
                      </span>

                      {submission.status === "pending" ? (
                        <span data-testid={`submission-row-${submission.id}-status`}>
                          <Badge>
                            {submission.pending_reason === "budget_exhausted" ? "채점 대기" : "채점 중"}
                          </Badge>
                        </span>
                      ) : (
                        <span data-testid={`submission-row-${submission.id}-status`}>
                          <Badge tone={submission.passed ? "verified" : "attention"}>
                            채점 완료 · {submission.passed ? "통과" : "미통과"}
                          </Badge>
                        </span>
                      )}

                      <span className="ml-auto shrink-0 text-[12.5px]">
                        {submission.submission_format === "repository" ? (
                          <a
                            href={submission.value}
                            target="_blank"
                            rel="noreferrer"
                            className="text-attention hover:underline"
                          >
                            {submission.value}
                          </a>
                        ) : submission.download_url ? (
                          <a
                            href={submission.download_url}
                            data-testid={`submission-row-${submission.id}-download`}
                            className="text-attention hover:underline"
                          >
                            다운로드
                          </a>
                        ) : null}
                      </span>
                    </div>

                    {submission.status === "pending" && submission.pending_reason === "budget_exhausted" ? (
                      // 「고장」이 아니라 「멈췄고 안전하다」로 읽혀야 한다
                      // (docs/design/classroom/README.md).
                      <p className="mt-2.5 text-[12.5px] leading-relaxed text-ink/60">
                        이 클래스의 채점 예산이 소진되어 잠시 멈췄습니다.{" "}
                        <b className="font-medium text-ink">제출은 저장됐으니 다시 낼 필요는 없습니다.</b>{" "}
                        예산이 채워지면 순서대로 이어서 채점됩니다.
                      </p>
                    ) : null}

                    {submission.status === "scored" && submission.score ? (
                      <ul
                        data-testid={`submission-row-${submission.id}-verdicts`}
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
                              {checklistLabelById.get(verdict.checklist_item_id) ?? "항목"}
                              <span className="text-ink/45"> — {verdict.is_met ? "충족" : "미충족"}</span>
                              <span className="block text-ink/60">{verdict.reasoning}</span>
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </div>

        <div className="flex w-full shrink-0 flex-col gap-4 lg:w-[380px]">
          <Card>
            <CardHeader title="제출" />
            <div className="flex flex-col gap-3.5 p-4">
              {problem.submission_format === "repository" ? (
                <form onSubmit={handleRepositorySubmit} className="flex flex-col gap-3">
                  <div className="flex flex-col gap-1.5">
                    <label htmlFor="repository-url">
                      <FieldLabel>GitHub 저장소 주소</FieldLabel>
                    </label>
                    <input
                      id="repository-url"
                      data-testid="repository-url-input"
                      type="url"
                      placeholder="https://github.com/owner/repo"
                      value={repositoryUrl}
                      onChange={(event) => setRepositoryUrl(event.target.value)}
                      required
                      className={`${INPUT_CLASS} font-mono`}
                    />
                  </div>
                  <button
                    type="submit"
                    data-testid="submit-repository"
                    disabled={submitting || repositoryUrl.trim() === ""}
                    className={`${buttonClass("primary")} w-full`}
                  >
                    {submitting ? "제출하는 중..." : "제출하기"}
                  </button>
                </form>
              ) : (
                <div className="flex flex-col gap-2">
                  <label htmlFor="source-file">
                    <FieldLabel>소스 파일</FieldLabel>
                  </label>
                  <input
                    id="source-file"
                    data-testid="source-file-input"
                    type="file"
                    onChange={handleSourceFile}
                    disabled={submitting || uploadState.status === "uploading"}
                    className="w-full cursor-pointer border border-dashed border-rule bg-paper px-3 py-6 text-[13px] text-ink/60 file:mr-3 file:cursor-pointer file:border file:border-rule file:bg-surface file:px-3 file:py-1.5 file:text-[12.5px] file:text-ink disabled:cursor-not-allowed disabled:opacity-45"
                  />
                  {uploadState.status === "uploading" ? (
                    <p data-testid="source-upload-progress" className="text-[12.5px] text-ink/45">
                      업로드하는 중...
                    </p>
                  ) : null}
                  {uploadState.status === "error" ? (
                    <ErrorNote>
                      <span data-testid="source-upload-error">{uploadState.error}</span>
                    </ErrorNote>
                  ) : null}
                </div>
              )}

              {submitError ? (
                <ErrorNote>
                  <span data-testid="submit-error">{submitError}</span>
                </ErrorNote>
              ) : null}

              <p className="text-[11.5px] leading-relaxed text-ink/45">
                <b className="font-medium text-ink">마감이 없습니다.</b> 몇 번이든 다시 낼 수 있고,
                낼 때마다 바로 채점이 시작됩니다. 한 번이라도 통과하면 통과로 셉니다 — 고치다 깨져도
                사라지지 않습니다.
              </p>
            </div>
          </Card>

          <Note>
            근거를 따로 연결하거나 자가 체크를 하지 않습니다 — 채점이 낸 소스에서 직접 판정합니다.
          </Note>
        </div>
      </div>
    </PageShell>
  );
}
