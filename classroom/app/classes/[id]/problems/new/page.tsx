"use client";

// 새 문제 (#282, #315). 제목·설명·제출 형식과 함께 체크리스트 항목을 그
// 자리에서 적는다 — 만들기 요청 하나가 문제와 항목을 함께 만든다. 항목이
// 준비됐으면(필수 항목이 하나 이상) 그 자리에서 바로 열 수도 있다. 마감을
// 넣을 자리는 애초에 없다.
import { useParams, useRouter } from "next/navigation";
import { useRef, useState } from "react";
import type { FormEvent } from "react";

import {
  Card,
  CardHeader,
  EmptyState,
  ErrorNote,
  FieldLabel,
  INPUT_CLASS,
  Note,
  PageHeader,
  PageShell,
  buttonClass,
} from "@/app/components/ui";
import { MarkdownEditor } from "@/app/components/MarkdownEditor";
import { BackendError } from "@/lib/backend/client";
import { createProblem, type SubmissionFormat } from "@/lib/problems/api";

type DraftChecklistItem = {
  key: number;
  label: string;
  required: boolean;
};

export default function NewProblemPage() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const router = useRouter();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [submissionFormat, setSubmissionFormat] = useState<SubmissionFormat>("source");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const nextKeyRef = useRef(0);
  const [items, setItems] = useState<DraftChecklistItem[]>([]);
  const [newItemLabel, setNewItemLabel] = useState("");
  const [newItemRequired, setNewItemRequired] = useState(true);

  const hasRequiredItem = items.some((item) => item.required);

  function handleAddItem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const label = newItemLabel.trim();
    if (label === "") return;
    setItems((prev) => [...prev, { key: nextKeyRef.current++, label, required: newItemRequired }]);
    setNewItemLabel("");
    setNewItemRequired(true);
  }

  function handleItemLabelChange(key: number, label: string) {
    setItems((prev) => prev.map((item) => (item.key === key ? { ...item, label } : item)));
  }

  function handleItemRequiredChange(key: number, required: boolean) {
    setItems((prev) => prev.map((item) => (item.key === key ? { ...item, required } : item)));
  }

  function handleItemDelete(key: number) {
    setItems((prev) => prev.filter((item) => item.key !== key));
  }

  function handleItemMove(key: number, direction: "up" | "down") {
    setItems((prev) => {
      const index = prev.findIndex((item) => item.key === key);
      const swapWith = direction === "up" ? index - 1 : index + 1;
      if (index < 0 || swapWith < 0 || swapWith >= prev.length) return prev;
      const reordered = [...prev];
      [reordered[index], reordered[swapWith]] = [reordered[swapWith], reordered[index]];
      return reordered;
    });
  }

  async function submitProblem(open: boolean) {
    if (title.trim() === "") return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await createProblem(classId, {
        title: title.trim(),
        description,
        submission_format: submissionFormat,
        checklist_items: items.map((item) => ({ label: item.label, required: item.required })),
        open,
      });
      router.push(`/classes/${classId}/problems/${created.id}`);
    } catch (err) {
      if (err instanceof BackendError) {
        setError(err.message);
      } else {
        setError("문제를 만들지 못했습니다. 잠시 후 다시 시도해주세요.");
      }
      setSubmitting(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitProblem(false);
  }

  function handleCreateAndOpen() {
    void submitProblem(true);
  }

  return (
    <PageShell>
      <PageHeader
        eyebrow="클래스 · 문제"
        title="새 문제"
        titleTestId="new-problem-heading"
        description="마감이 없습니다. 참여자는 몇 번이든 다시 낼 수 있고, 낼 때마다 바로 채점됩니다."
      />

      <div className="flex max-w-[720px] flex-col gap-5">
        <Card>
          <form id="new-problem-form" onSubmit={handleSubmit} className="flex flex-col gap-5 p-5">
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
                className={INPUT_CLASS}
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
                제출된 내용만 보고 채점합니다 — 참여자가 따로 근거를 적거나 스스로 체크할
                필요는 없습니다.
              </span>
            </fieldset>
          </form>
        </Card>

        <Card>
          <CardHeader
            title="체크리스트"
            hint="채점이 항목마다 소스를 읽어 판정합니다 — 필수를 전부 충족하면 「통과」"
          />
          {items.length === 0 ? (
            <EmptyState>
              <span data-testid="new-problem-checklist-empty-state">
                아직 항목이 없습니다. 항목 없이 만들면 초안으로 남아 나중에 이어서 추가할 수
                있습니다.
              </span>
            </EmptyState>
          ) : (
            <ul data-testid="new-problem-checklist-items" className="divide-y divide-rule">
              {items.map((item, index) => (
                <li
                  key={item.key}
                  data-testid={`new-problem-checklist-item-${index}`}
                  className="flex flex-wrap items-center gap-2 px-4 py-3"
                >
                  <span className="w-4 shrink-0 font-mono text-[11.5px] text-ink/30">{index + 1}</span>
                  <input
                    data-testid={`new-problem-checklist-item-${index}-label-input`}
                    value={item.label}
                    onChange={(event) => handleItemLabelChange(item.key, event.target.value)}
                    className={`${INPUT_CLASS} min-w-[200px] flex-1`}
                  />
                  <label className="flex shrink-0 items-center gap-1.5 text-[12.5px]">
                    <input
                      type="checkbox"
                      data-testid={`new-problem-checklist-item-${index}-required-input`}
                      checked={item.required}
                      onChange={(event) => handleItemRequiredChange(item.key, event.target.checked)}
                      className="accent-attention"
                    />
                    필수
                  </label>
                  <span className="flex shrink-0 gap-1">
                    <button
                      type="button"
                      data-testid={`new-problem-checklist-item-${index}-move-up`}
                      disabled={index === 0}
                      onClick={() => handleItemMove(item.key, "up")}
                      className={buttonClass("secondary", "sm")}
                    >
                      위로
                    </button>
                    <button
                      type="button"
                      data-testid={`new-problem-checklist-item-${index}-move-down`}
                      disabled={index === items.length - 1}
                      onClick={() => handleItemMove(item.key, "down")}
                      className={buttonClass("secondary", "sm")}
                    >
                      아래로
                    </button>
                    <button
                      type="button"
                      data-testid={`new-problem-checklist-item-${index}-delete`}
                      onClick={() => handleItemDelete(item.key)}
                      className={buttonClass("danger", "sm")}
                    >
                      삭제
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          )}

          <form
            onSubmit={handleAddItem}
            className="flex flex-wrap items-center gap-2 border-t border-rule p-4"
          >
            <label htmlFor="new-item-label" className="sr-only">
              새 항목
            </label>
            <input
              id="new-item-label"
              data-testid="new-problem-new-checklist-item-label-input"
              value={newItemLabel}
              onChange={(event) => setNewItemLabel(event.target.value)}
              placeholder="새 항목 — 채점이 이 문장으로 판정합니다"
              className={`${INPUT_CLASS} min-w-[220px] flex-1`}
            />
            <label className="flex shrink-0 items-center gap-1.5 text-[12.5px]">
              <input
                type="checkbox"
                data-testid="new-problem-new-checklist-item-required-input"
                checked={newItemRequired}
                onChange={(event) => setNewItemRequired(event.target.checked)}
                className="accent-attention"
              />
              필수
            </label>
            <button
              type="submit"
              data-testid="new-problem-new-checklist-item-submit"
              disabled={newItemLabel.trim() === ""}
              className={buttonClass("primary", "sm")}
            >
              추가
            </button>
          </form>
        </Card>

        {!hasRequiredItem ? (
          <Note tone="attention">
            <span data-testid="new-problem-open-blocked-notice">
              필수 항목이 하나도 없어 바로 열 수 없습니다. 항목을 추가하고 하나 이상을 필수로
              표시하면 「만들고 바로 열기」를 쓸 수 있습니다 — 초안으로만 만들어 두고 나중에
              이어 쓸 수도 있습니다.
            </span>
          </Note>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="submit"
            form="new-problem-form"
            data-testid="new-problem-submit"
            disabled={submitting || title.trim() === ""}
            className={buttonClass("secondary")}
          >
            {submitting ? "만드는 중..." : "만들기"}
          </button>
          <button
            type="button"
            data-testid="new-problem-create-and-open-submit"
            disabled={submitting || title.trim() === "" || !hasRequiredItem}
            onClick={handleCreateAndOpen}
            className={buttonClass("primary")}
          >
            {submitting ? "만드는 중..." : "만들고 바로 열기"}
          </button>
        </div>

        {error ? (
          <ErrorNote>
            <span data-testid="new-problem-error">{error}</span>
          </ErrorNote>
        ) : null}
      </div>
    </PageShell>
  );
}
