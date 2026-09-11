"use client";

// 문제 편집 (#282/#283/#285). 제목·설명·제출 형식·채점 모델에 이어
// 체크리스트(필수·선택 항목과 순서)를 여기서 관리하고, 초안을 연다.
import Link from "next/link";

import {
  Badge,
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
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { BackendError } from "@/lib/backend/client";
import { useMyClasses } from "@/lib/classes/use-my-classes";
import {
  copyProblem,
  createChecklistItem,
  deleteChecklistItem,
  openProblem,
  reorderChecklistItems,
  updateChecklistItem,
  updateProblem,
  type SubmissionFormat,
} from "@/lib/problems/api";
import { useProblem } from "@/lib/problems/use-problem";
import { useScoringModels } from "@/lib/scoring/use-scoring-models";

export default function EditProblemPage() {
  const params = useParams<{ id: string; problemId: string }>();
  const classId = Number(params.id);
  const problemId = Number(params.problemId);
  const router = useRouter();

  const { state, reload } = useProblem(classId, problemId);
  const modelsState = useScoringModels();
  const myClassesState = useMyClasses();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [submissionFormat, setSubmissionFormat] = useState<SubmissionFormat>("source");
  const [model, setModel] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [newItemLabel, setNewItemLabel] = useState("");
  const [newItemRequired, setNewItemRequired] = useState(true);
  const [checklistError, setChecklistError] = useState<string | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);

  const [targetClassId, setTargetClassId] = useState("");
  const [copying, setCopying] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);

  useEffect(() => {
    if (state.status === "ready") {
      setTitle(state.problem.title);
      setDescription(state.problem.description);
      setSubmissionFormat(state.problem.submission_format);
      setModel(state.problem.model);
    }
  }, [state]);

  if (state.status === "loading") {
    return (
      <PageShell>
        <p data-testid="edit-problem-loading" className="text-[13.5px] text-ink/45">불러오는 중...</p>
      </PageShell>
    );
  }

  if (state.status === "error") {
    return (
      <PageShell>
        <p data-testid="edit-problem-error" className="text-[15px]">문제를 찾을 수 없습니다.</p>
      </PageShell>
    );
  }

  const { problem } = state;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await updateProblem(classId, problemId, {
        title: title.trim(),
        description,
        submission_format: submissionFormat,
        model,
      });
      reload();
      router.push(`/classes/${classId}`);
    } catch {
      setError("문제를 저장하지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setSaving(false);
    }
  }

  async function handleAddItem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setChecklistError(null);
    try {
      await createChecklistItem(classId, problemId, {
        label: newItemLabel.trim(),
        required: newItemRequired,
      });
      setNewItemLabel("");
      setNewItemRequired(true);
      reload();
    } catch {
      setChecklistError("항목을 추가하지 못했습니다. 잠시 후 다시 시도해주세요.");
    }
  }

  async function handleItemLabelSave(itemId: number, label: string) {
    setChecklistError(null);
    try {
      await updateChecklistItem(classId, problemId, itemId, { label });
      reload();
    } catch {
      setChecklistError("항목을 저장하지 못했습니다. 잠시 후 다시 시도해주세요.");
    }
  }

  async function handleItemRequiredToggle(itemId: number, required: boolean) {
    setChecklistError(null);
    try {
      await updateChecklistItem(classId, problemId, itemId, { required });
      reload();
    } catch {
      setChecklistError("항목을 저장하지 못했습니다. 잠시 후 다시 시도해주세요.");
    }
  }

  async function handleItemDelete(itemId: number) {
    setChecklistError(null);
    try {
      await deleteChecklistItem(classId, problemId, itemId);
      reload();
    } catch {
      setChecklistError("항목을 지우지 못했습니다. 잠시 후 다시 시도해주세요.");
    }
  }

  async function handleItemMove(itemId: number, direction: "up" | "down") {
    const items = problem.checklist_items;
    const index = items.findIndex((i) => i.id === itemId);
    const swapWith = direction === "up" ? index - 1 : index + 1;
    if (index < 0 || swapWith < 0 || swapWith >= items.length) return;

    const reordered = [...items];
    [reordered[index], reordered[swapWith]] = [reordered[swapWith], reordered[index]];

    setChecklistError(null);
    try {
      await reorderChecklistItems(
        classId,
        problemId,
        reordered.map((i) => i.id),
      );
      reload();
    } catch {
      setChecklistError("순서를 바꾸지 못했습니다. 다시 시도해주세요.");
    }
  }

  async function handleCopy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCopyError(null);
    setCopying(true);
    try {
      const copy = await copyProblem(classId, problemId, Number(targetClassId));
      router.push(`/classes/${copy.classroom_id}/problems/${copy.id}`);
    } catch {
      setCopyError("문제를 복사하지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setCopying(false);
    }
  }

  async function handleOpen() {
    setOpenError(null);
    try {
      await openProblem(classId, problemId);
      reload();
    } catch (err) {
      if (err instanceof BackendError) {
        setOpenError(err.message);
      } else {
        setOpenError("문제를 열지 못했습니다. 잠시 후 다시 시도해주세요.");
      }
    }
  }

  return (
    <PageShell>
      <PageHeader
        eyebrow="클래스 · 문제"
        title="문제 편집"
        titleTestId="edit-problem-heading"
        description="마감이 없습니다. 이미 푼 사람이 있어도 언제든 고칠 수 있습니다."
        actions={
          <>
            <Badge tone={problem.status === "open" ? "verified" : "neutral"}>
              {problem.status === "open" ? "열림" : "초안"}
            </Badge>
            <Link
              href={`/classes/${classId}/problems/${problemId}/submissions`}
              data-testid="problem-submissions-link"
              className={buttonClass()}
            >
              제출 현황 보기
            </Link>
            {problem.status === "open" ? null : (
              <button
                type="button"
                data-testid="open-problem-button"
                onClick={handleOpen}
                className={buttonClass("primary")}
              >
                문제 열기
              </button>
            )}
          </>
        }
      />

      <div className="flex flex-col gap-5">
        {problem.status === "open" ? (
          // 이미 열린 문제는 참여자가 이미 시도했을 수 있다. 체크리스트를 고쳐도
          // 지난 점수는 남고 달성률만 새 기준으로 다시 셈된다는 것을 미리
          // 알린다(CONTEXT.md 「Problem」).
          <Note tone="attention">
            <span data-testid="edit-problem-open-notice">
              이미 열린 문제입니다. 체크리스트를 바꿔도 지난 시도의 점수는 그대로 남고 달성률만 새
              기준으로 다시 계산됩니다.
            </span>
          </Note>
        ) : null}
        {openError ? (
          <ErrorNote>
            <span data-testid="open-problem-error">{openError}</span>
          </ErrorNote>
        ) : null}

        <div className="flex flex-col gap-5 lg:flex-row lg:items-start">
          <div className="flex min-w-0 flex-1 flex-col gap-5">
            <Card>
              <CardHeader title="문제" />
              <form onSubmit={handleSubmit} className="flex flex-col gap-5 p-4">
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="problem-title">
                    <FieldLabel>제목</FieldLabel>
                  </label>
                  <input
                    id="problem-title"
                    data-testid="edit-problem-title-input"
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                    required
                    className={INPUT_CLASS}
                  />
                </div>

                <div className="flex flex-col gap-1.5">
                  <label htmlFor="problem-description">
                    <FieldLabel>설명</FieldLabel>
                  </label>
                  <MarkdownEditor
                    id="problem-description"
                    testId="edit-problem-description-input"
                    value={description}
                    onChange={setDescription}
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
                        data-testid="edit-problem-format-source"
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
                        data-testid="edit-problem-format-repository"
                        className="accent-ink"
                      />
                      저장소
                    </label>
                  </div>
                </fieldset>

                <div>
                  <button
                    type="submit"
                    data-testid="edit-problem-submit"
                    disabled={saving || title.trim() === ""}
                    className={buttonClass("primary")}
                  >
                    {saving ? "저장하는 중..." : "저장"}
                  </button>
                </div>

                {error ? (
                  <ErrorNote>
                    <span data-testid="edit-problem-error-message">{error}</span>
                  </ErrorNote>
                ) : null}
              </form>
            </Card>

            <Card>
              <CardHeader title="체크리스트" hint="필수를 전부 충족하면 「통과」" />
              {problem.checklist_items.length === 0 ? (
                <EmptyState>
                  <span data-testid="checklist-empty-state">아직 항목이 없습니다.</span>
                </EmptyState>
              ) : (
                <ul data-testid="checklist-items" className="divide-y divide-rule">
                  {problem.checklist_items.map((item, index) => (
                    <li
                      key={item.id}
                      data-testid={`checklist-item-${item.id}`}
                      className="flex flex-wrap items-center gap-2 px-4 py-3"
                    >
                      <span className="w-4 shrink-0 font-mono text-[11.5px] text-ink/30">{index + 1}</span>
                      <input
                        data-testid={`checklist-item-${item.id}-label-input`}
                        defaultValue={item.label}
                        onBlur={(event) => {
                          if (event.target.value.trim() !== "" && event.target.value !== item.label) {
                            handleItemLabelSave(item.id, event.target.value.trim());
                          }
                        }}
                        className={`${INPUT_CLASS} min-w-[200px] flex-1`}
                      />
                      <label className="flex shrink-0 items-center gap-1.5 text-[12.5px]">
                        <input
                          type="checkbox"
                          data-testid={`checklist-item-${item.id}-required-input`}
                          checked={item.required}
                          onChange={(event) => handleItemRequiredToggle(item.id, event.target.checked)}
                          className="accent-attention"
                        />
                        필수
                      </label>
                      <span className="flex shrink-0 gap-1">
                        <button
                          type="button"
                          data-testid={`checklist-item-${item.id}-move-up`}
                          disabled={index === 0}
                          onClick={() => handleItemMove(item.id, "up")}
                          className={buttonClass("secondary", "sm")}
                        >
                          위로
                        </button>
                        <button
                          type="button"
                          data-testid={`checklist-item-${item.id}-move-down`}
                          disabled={index === problem.checklist_items.length - 1}
                          onClick={() => handleItemMove(item.id, "down")}
                          className={buttonClass("secondary", "sm")}
                        >
                          아래로
                        </button>
                        <button
                          type="button"
                          data-testid={`checklist-item-${item.id}-delete`}
                          onClick={() => handleItemDelete(item.id)}
                          className={buttonClass("danger", "sm")}
                        >
                          삭제
                        </button>
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              <form onSubmit={handleAddItem} className="flex flex-wrap items-center gap-2 border-t border-rule p-4">
                <label htmlFor="new-item-label" className="sr-only">
                  새 항목
                </label>
                <input
                  id="new-item-label"
                  data-testid="new-checklist-item-label-input"
                  value={newItemLabel}
                  onChange={(event) => setNewItemLabel(event.target.value)}
                  required
                  placeholder="새 항목 — 채점이 이 문장으로 판정합니다"
                  className={`${INPUT_CLASS} min-w-[220px] flex-1`}
                />
                <label className="flex shrink-0 items-center gap-1.5 text-[12.5px]">
                  <input
                    type="checkbox"
                    data-testid="new-checklist-item-required-input"
                    checked={newItemRequired}
                    onChange={(event) => setNewItemRequired(event.target.checked)}
                    className="accent-attention"
                  />
                  필수
                </label>
                <button
                  type="submit"
                  data-testid="new-checklist-item-submit"
                  disabled={newItemLabel.trim() === ""}
                  className={buttonClass("primary", "sm")}
                >
                  추가
                </button>
              </form>

              {checklistError ? (
                <div className="border-t border-rule p-4">
                  <ErrorNote>
                    <span data-testid="checklist-error">{checklistError}</span>
                  </ErrorNote>
                </div>
              ) : null}
            </Card>
          </div>

          <div className="flex w-full shrink-0 flex-col gap-5 lg:w-[380px]">
            <Card>
              <CardHeader title="채점 모델" />
              <div className="flex flex-col gap-2.5 p-4">
                <label htmlFor="problem-model" className="sr-only">
                  채점 모델
                </label>
                {modelsState.status === "ready" ? (
                  <select
                    id="problem-model"
                    data-testid="edit-problem-model-select"
                    value={model}
                    onChange={(event) => setModel(event.target.value)}
                    className={INPUT_CLASS}
                  >
                    <option value="" data-testid="edit-problem-model-option-inherit">
                      클래스 기본값을 따릅니다
                    </option>
                    {modelsState.models.map((option) => (
                      <option
                        key={option.id}
                        value={option.id}
                        data-testid={`edit-problem-model-option-${option.id}`}
                      >
                        {option.label} · 컨텍스트 {option.context_window.toLocaleString("ko-KR")} 토큰
                      </option>
                    ))}
                  </select>
                ) : (
                  <p data-testid="edit-problem-model-loading" className="text-[13px] text-ink/45">
                    모델 목록을 불러오는 중...
                  </p>
                )}
                {model === "" ? (
                  <p data-testid="edit-problem-model-effective" className="text-[12.5px] text-ink/60">
                    실제로 쓰일 모델: <span className="font-mono">{problem.effective_model}</span>
                  </p>
                ) : null}
                <span className="text-[11.5px] leading-relaxed text-ink/45">
                  문제 설명이 길면 컨텍스트가 작은 모델은 뒷부분이 잘린 채 채점됩니다 — 그래서
                  문제마다 다른 모델을 고를 수 있습니다.
                </span>
              </div>
            </Card>

            <Card>
              <CardHeader title="다른 클래스로 복사" />
              <div className="flex flex-col gap-2.5 p-4">
                {myClassesState.status === "ready" ? (
                  (() => {
                    const otherClasses = myClassesState.classes.filter((c) => c.id !== classId);
                    if (otherClasses.length === 0) {
                      return (
                        <p data-testid="copy-problem-no-target" className="text-[13px] text-ink/45">
                          복사할 다른 클래스가 없습니다.
                        </p>
                      );
                    }
                    return (
                      <form onSubmit={handleCopy} className="flex flex-col gap-2.5">
                        <label htmlFor="copy-problem-target">
                          <FieldLabel>대상 클래스</FieldLabel>
                        </label>
                        <select
                          id="copy-problem-target"
                          data-testid="copy-problem-target-select"
                          value={targetClassId}
                          onChange={(event) => setTargetClassId(event.target.value)}
                          className={INPUT_CLASS}
                        >
                          <option value="" data-testid="copy-problem-target-option-empty">
                            클래스를 선택하세요
                          </option>
                          {otherClasses.map((c) => (
                            <option key={c.id} value={c.id} data-testid={`copy-problem-target-option-${c.id}`}>
                              {c.name}
                            </option>
                          ))}
                        </select>
                        <button
                          type="submit"
                          data-testid="copy-problem-submit"
                          disabled={copying || targetClassId === ""}
                          className={buttonClass("secondary")}
                        >
                          {copying ? "복사하는 중..." : "복사"}
                        </button>
                      </form>
                    );
                  })()
                ) : (
                  <p data-testid="copy-problem-classes-loading" className="text-[13px] text-ink/45">
                    클래스 목록을 불러오는 중...
                  </p>
                )}
                {copyError ? (
                  <ErrorNote>
                    <span data-testid="copy-problem-error">{copyError}</span>
                  </ErrorNote>
                ) : null}
                <span className="text-[11.5px] leading-relaxed text-ink/45">
                  체크리스트와 채점 설정이 함께 옵니다. 제출물·점수는 따라오지 않고, 복사본은
                  대상 클래스에서 초안으로 들어옵니다.
                </span>
              </div>
            </Card>
          </div>
        </div>
      </div>
    </PageShell>
  );
}
