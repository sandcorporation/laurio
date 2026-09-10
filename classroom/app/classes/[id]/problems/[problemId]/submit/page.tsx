"use client";

// 참여자 제출 화면 (#286). 소스 또는 저장소를 내고, 낼 때마다 새 시도가
// 시도 목록에 쌓인다 — 마감도 횟수 상한도 없다(CONTEXT.md 「Problem」).
// 강사 전용 편집 화면(app/classes/[id]/problems/[problemId]/page.tsx)과는
// 다른 라우트다 — 참여자는 문제를 고치지 않고 그 정의를 읽고 낸다.
import { useParams } from "next/navigation";
import { useState } from "react";
import type { ChangeEvent, FormEvent } from "react";

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
      <main>
        <p data-testid="my-problem-loading">불러오는 중...</p>
      </main>
    );
  }

  if (state.status === "notFound") {
    return (
      <main>
        <h1 data-testid="my-problem-not-found">문제를 찾을 수 없습니다</h1>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main>
        <p data-testid="my-problem-error">문제 정보를 불러오지 못했습니다.</p>
      </main>
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

  return (
    <main>
      <h1 data-testid="my-problem-title">{problem.title}</h1>
      <p data-testid="my-problem-passed-status">
        {problem.passed ? "이 문제를 통과했습니다" : "아직 통과하지 못했습니다"}
      </p>
      {problem.description ? <p data-testid="my-problem-description">{problem.description}</p> : null}

      <section>
        <h2>체크리스트</h2>
        <ul data-testid="my-problem-checklist">
          {problem.checklist_items.map((item) => (
            <li key={item.id} data-testid={`checklist-item-${item.id}`}>
              {item.label} {item.required ? "(필수)" : "(선택)"}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2>제출</h2>
        {problem.submission_format === "repository" ? (
          <form onSubmit={handleRepositorySubmit}>
            <label htmlFor="repository-url">GitHub 저장소 주소</label>
            <input
              id="repository-url"
              data-testid="repository-url-input"
              type="url"
              placeholder="https://github.com/owner/repo"
              value={repositoryUrl}
              onChange={(event) => setRepositoryUrl(event.target.value)}
              required
            />
            <button
              type="submit"
              data-testid="submit-repository"
              disabled={submitting || repositoryUrl.trim() === ""}
            >
              {submitting ? "제출하는 중..." : "제출"}
            </button>
          </form>
        ) : (
          <div>
            <label htmlFor="source-file">소스 파일</label>
            <input
              id="source-file"
              data-testid="source-file-input"
              type="file"
              onChange={handleSourceFile}
              disabled={submitting || uploadState.status === "uploading"}
            />
            {uploadState.status === "uploading" ? (
              <p data-testid="source-upload-progress">업로드하는 중...</p>
            ) : null}
            {uploadState.status === "error" ? (
              <p data-testid="source-upload-error">{uploadState.error}</p>
            ) : null}
          </div>
        )}
        {submitError ? <p data-testid="submit-error">{submitError}</p> : null}
      </section>

      <section>
        <h2>내 시도</h2>
        {submissions.length === 0 ? (
          <p data-testid="submissions-empty-state">아직 낸 시도가 없습니다.</p>
        ) : (
          <ol data-testid="submissions-list">
            {submissions.map((submission) => {
              const checklistLabelById = new Map(
                problem.checklist_items.map((item) => [item.id, item.label]),
              );
              return (
                <li key={submission.id} data-testid={`submission-row-${submission.id}`}>
                  <span data-testid={`submission-row-${submission.id}-attempt`}>
                    {submission.attempt_number}번째 시도
                  </span>{" "}
                  ·{" "}
                  {submission.submission_format === "repository" ? (
                    <a href={submission.value} target="_blank" rel="noreferrer">
                      {submission.value}
                    </a>
                  ) : submission.download_url ? (
                    <a
                      href={submission.download_url}
                      data-testid={`submission-row-${submission.id}-download`}
                    >
                      다운로드
                    </a>
                  ) : null}{" "}
                  ·{" "}
                  {submission.status === "pending" ? (
                    <span data-testid={`submission-row-${submission.id}-status`}>채점 중</span>
                  ) : (
                    <span data-testid={`submission-row-${submission.id}-status`}>
                      채점 완료 · {submission.passed ? "통과" : "미통과"}
                    </span>
                  )}
                  {submission.status === "scored" && submission.score ? (
                    <ul data-testid={`submission-row-${submission.id}-verdicts`}>
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
              );
            })}
          </ol>
        )}
      </section>
    </main>
  );
}
