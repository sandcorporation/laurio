"use client";

// 문제 편집 (#282/#283). 제목·설명·제출 형식에 이어 체크리스트(필수·선택
// 항목과 순서)를 여기서 관리하고, 초안을 연다.
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { BackendError } from "@/lib/backend/client";
import {
  createChecklistItem,
  deleteChecklistItem,
  openProblem,
  reorderChecklistItems,
  updateChecklistItem,
  updateProblem,
  type SubmissionFormat,
} from "@/lib/problems/api";
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

  const [newItemLabel, setNewItemLabel] = useState("");
  const [newItemRequired, setNewItemRequired] = useState(true);
  const [checklistError, setChecklistError] = useState<string | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);

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
    <main>
      <h1 data-testid="edit-problem-heading">문제 편집</h1>

      {problem.status === "open" ? (
        // 이미 열린 문제는 참여자가 이미 시도했을 수 있다. 체크리스트를 고쳐도
        // 지난 점수는 남고 달성률만 새 기준으로 다시 셈된다는 것을 미리
        // 알린다(CONTEXT.md 「Problem」).
        <p data-testid="edit-problem-open-notice">
          이미 열린 문제입니다. 체크리스트를 바꿔도 지난 시도의 점수는 그대로 남고
          달성률만 새 기준으로 다시 계산됩니다.
        </p>
      ) : (
        <div>
          <button type="button" data-testid="open-problem-button" onClick={handleOpen}>
            문제 열기
          </button>
          {openError ? <p data-testid="open-problem-error">{openError}</p> : null}
        </div>
      )}

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

      <h2>체크리스트</h2>
      <p>필수 항목을 전부 충족해야 통과입니다 — 참여자도 무엇이 필수인지 볼 수 있습니다.</p>

      {problem.checklist_items.length === 0 ? (
        <p data-testid="checklist-empty-state">아직 항목이 없습니다.</p>
      ) : (
        <ul data-testid="checklist-items">
          {problem.checklist_items.map((item, index) => (
            <li key={item.id} data-testid={`checklist-item-${item.id}`}>
              <input
                data-testid={`checklist-item-${item.id}-label-input`}
                defaultValue={item.label}
                onBlur={(event) => {
                  if (event.target.value.trim() !== "" && event.target.value !== item.label) {
                    handleItemLabelSave(item.id, event.target.value.trim());
                  }
                }}
              />
              <label>
                <input
                  type="checkbox"
                  data-testid={`checklist-item-${item.id}-required-input`}
                  checked={item.required}
                  onChange={(event) => handleItemRequiredToggle(item.id, event.target.checked)}
                />
                필수
              </label>
              <button
                type="button"
                data-testid={`checklist-item-${item.id}-move-up`}
                disabled={index === 0}
                onClick={() => handleItemMove(item.id, "up")}
              >
                위로
              </button>
              <button
                type="button"
                data-testid={`checklist-item-${item.id}-move-down`}
                disabled={index === problem.checklist_items.length - 1}
                onClick={() => handleItemMove(item.id, "down")}
              >
                아래로
              </button>
              <button
                type="button"
                data-testid={`checklist-item-${item.id}-delete`}
                onClick={() => handleItemDelete(item.id)}
              >
                삭제
              </button>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={handleAddItem}>
        <label htmlFor="new-item-label">새 항목</label>
        <input
          id="new-item-label"
          data-testid="new-checklist-item-label-input"
          value={newItemLabel}
          onChange={(event) => setNewItemLabel(event.target.value)}
          required
        />
        <label>
          <input
            type="checkbox"
            data-testid="new-checklist-item-required-input"
            checked={newItemRequired}
            onChange={(event) => setNewItemRequired(event.target.checked)}
          />
          필수
        </label>
        <button type="submit" data-testid="new-checklist-item-submit" disabled={newItemLabel.trim() === ""}>
          추가
        </button>
      </form>

      {checklistError ? <p data-testid="checklist-error">{checklistError}</p> : null}
    </main>
  );
}
