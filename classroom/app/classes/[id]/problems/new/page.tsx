"use client";

// 새 문제 (#282). 제목·설명·제출 형식만 받는다 — 마감을 넣을 자리는 애초에
// 없다. 체크리스트는 문제를 만든 뒤 편집 화면에서 붙인다(#283).
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import type { FormEvent } from "react";

import { createProblem, type SubmissionFormat } from "@/lib/problems/api";

export default function NewProblemPage() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const router = useRouter();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [submissionFormat, setSubmissionFormat] = useState<SubmissionFormat>("source");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const created = await createProblem(classId, {
        title: title.trim(),
        description,
        submission_format: submissionFormat,
      });
      router.push(`/classes/${classId}/problems/${created.id}`);
    } catch {
      setError("문제를 만들지 못했습니다. 잠시 후 다시 시도해주세요.");
      setSubmitting(false);
    }
  }

  return (
    <main>
      <h1 data-testid="new-problem-heading">새 문제</h1>

      <form onSubmit={handleSubmit}>
        <label htmlFor="problem-title">제목</label>
        <input
          id="problem-title"
          data-testid="new-problem-title-input"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          required
        />

        <label htmlFor="problem-description">설명</label>
        <textarea
          id="problem-description"
          data-testid="new-problem-description-input"
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
              data-testid="new-problem-format-source"
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
              data-testid="new-problem-format-repository"
            />
            저장소
          </label>
        </fieldset>

        <button type="submit" data-testid="new-problem-submit" disabled={submitting || title.trim() === ""}>
          {submitting ? "만드는 중..." : "만들기"}
        </button>
      </form>

      {error ? <p data-testid="new-problem-error">{error}</p> : null}
    </main>
  );
}
