"use client";

// 새 문제 (#282). 제목·설명·제출 형식만 받는다 — 마감을 넣을 자리는 애초에
// 없다. 체크리스트는 문제를 만든 뒤 편집 화면에서 붙인다(#283).
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import type { FormEvent } from "react";

import {
  Card,
  ErrorNote,
  FieldLabel,
  INPUT_CLASS,
  PageHeader,
  PageShell,
  buttonClass,
} from "@/app/components/ui";
import { MarkdownEditor } from "@/app/components/MarkdownEditor";
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
    <PageShell>
      <PageHeader
        eyebrow="클래스 · 문제"
        title="새 문제"
        titleTestId="new-problem-heading"
        description="마감이 없습니다. 참여자는 몇 번이든 다시 낼 수 있고, 낼 때마다 바로 채점됩니다. 체크리스트는 만든 뒤 문제 화면에서 붙입니다."
      />

      <Card className="p-5">
        <form onSubmit={handleSubmit} className="flex flex-col gap-5">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="problem-title">
              <FieldLabel>제목</FieldLabel>
            </label>
            <input
              id="problem-title"
              data-testid="new-problem-title-input"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              required
              className={`${INPUT_CLASS} max-w-[720px]`}
              placeholder="예: fetch 로 목록 그리기"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="problem-description">
              <FieldLabel>설명</FieldLabel>
            </label>
            <MarkdownEditor
              id="problem-description"
              testId="new-problem-description-input"
              value={description}
              onChange={setDescription}
              placeholder="무엇을 만들어야 하는지, 그리고 무엇이 이 문제의 핵심인지."
            />
          </div>

          <fieldset className="flex flex-col gap-1.5">
            <legend>
              <FieldLabel>제출 형식</FieldLabel>
            </legend>
            <div className="flex flex-col gap-2 pt-1">
              <label className="flex items-center gap-2.5 text-[13.5px]">
                <input
                  type="radio"
                  name="submission_format"
                  value="source"
                  checked={submissionFormat === "source"}
                  onChange={() => setSubmissionFormat("source")}
                  data-testid="new-problem-format-source"
                  className="accent-ink"
                />
                소스
              </label>
              <label className="flex items-center gap-2.5 text-[13.5px]">
                <input
                  type="radio"
                  name="submission_format"
                  value="repository"
                  checked={submissionFormat === "repository"}
                  onChange={() => setSubmissionFormat("repository")}
                  data-testid="new-problem-format-repository"
                  className="accent-ink"
                />
                저장소
              </label>
            </div>
            <span className="text-[11.5px] leading-relaxed text-ink/45">
              근거 연결도 자가 체크도 없습니다 — 채점이 소스에서 직접 판정합니다.
            </span>
          </fieldset>

          <div>
            <button
              type="submit"
              data-testid="new-problem-submit"
              disabled={submitting || title.trim() === ""}
              className={buttonClass("primary")}
            >
              {submitting ? "만드는 중..." : "만들기"}
            </button>
          </div>

          {error ? (
            <ErrorNote>
              <span data-testid="new-problem-error">{error}</span>
            </ErrorNote>
          ) : null}
        </form>
      </Card>
    </PageShell>
  );
}
