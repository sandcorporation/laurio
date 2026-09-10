"use client";

// 문제 편집 (#282). 제목·설명·제출 형식을 고친다. 체크리스트는 #283이 이
// 화면에 이어 붙인다.
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { updateProblem, type SubmissionFormat } from "@/lib/problems/api";
import { useProblem } from "@/lib/problems/use-problem";

export default function EditProblemPage() {
  const params = useParams<{ id: string; problemId: string }>();
  const classId = Number(params.id);
  const problemId = Number(params.problemId);
  const router = useRouter();

  const { state, reload } = useProblem(classId, problemId);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [submissionFormat, setSubmissionFormat] = useState<SubmissionFormat>("source");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (state.status === "ready") {
      setTitle(state.problem.title);
      setDescription(state.problem.description);
      setSubmissionFormat(state.problem.submission_format);
    }
  }, [state]);

  if (state.status === "loading") {
    return (
      <main>
        <p data-testid="edit-problem-loading">불러오는 중...</p>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main>
        <p data-testid="edit-problem-error">문제를 찾을 수 없습니다.</p>
      </main>
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await updateProblem(classId, problemId, {
        title: title.trim(),
        description,
        submission_format: submissionFormat,
      });
      reload();
      router.push(`/classes/${classId}`);
    } catch {
      setError("문제를 저장하지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main>
      <h1 data-testid="edit-problem-heading">문제 편집</h1>

      <form onSubmit={handleSubmit}>
        <label htmlFor="problem-title">제목</label>
        <input
          id="problem-title"
          data-testid="edit-problem-title-input"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          required
        />

        <label htmlFor="problem-description">설명</label>
        <textarea
          id="problem-description"
          data-testid="edit-problem-description-input"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />

        <fieldset>
          <legend>제출 형식</legend>
          <label>
            <input
              type="radio"
              name="submission_format"
              value="source"
              checked={submissionFormat === "source"}
              onChange={() => setSubmissionFormat("source")}
              data-testid="edit-problem-format-source"
            />
            소스
          </label>
          <label>
            <input
              type="radio"
              name="submission_format"
              value="repository"
              checked={submissionFormat === "repository"}
              onChange={() => setSubmissionFormat("repository")}
              data-testid="edit-problem-format-repository"
            />
            저장소
          </label>
        </fieldset>

        <button type="submit" data-testid="edit-problem-submit" disabled={saving || title.trim() === ""}>
          {saving ? "저장하는 중..." : "저장"}
        </button>
      </form>

      {error ? <p data-testid="edit-problem-error-message">{error}</p> : null}
    </main>
  );
}
