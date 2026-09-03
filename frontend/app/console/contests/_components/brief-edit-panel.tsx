"use client";

// 브리프 수정 패널 (#113, 부모 #110).
//
// 결제가 문을 닫기 전까지는 제목·설명·카테고리·요구형태·상금·마감을 전부 고칠
// 수 있다. 이 컴포넌트는 순전히 폼이다 — 저장이 실제로 무엇을 바꾸는지(파생값
// 재계산 포함)는 전부 백엔드(`PATCH /contests/{id}`)가 판정한다. 이 화면은
// 그 결과를 그대로 받아 부모(draft/page.tsx)에게 새 Contest를 돌려줄 뿐, 최소
// 상금이나 미달 여부를 스스로 계산하지 않는다(#113 AC — "판정은 백엔드가
// 한다").
import { useState } from "react";

import { formatPrize } from "@/lib/contest-format";
import type { Category, ContestDetail, DeliverableType } from "@/lib/contests/grill-types";

export type BriefEditPatch = {
  title: string;
  category_id: number;
  deliverable_type_ids: number[];
  prize: number;
  deadline_at: string;
  description: string;
};

export interface BriefEditPanelProps {
  contest: ContestDetail;
  categories: Category[];
  deliverableTypes: DeliverableType[];
  saving: boolean;
  error: string | null;
  /** 요구형태가 방금 저장으로 바뀌었다 — 이미 붙인 Requirement는 지워지지
   * 않았지만, Sponsor가 스스로 검토하도록 화면이 알린다(spec #110). */
  deliverableTypesChangedNotice: boolean;
  onDismissDeliverableTypesChangedNotice: () => void;
  onSave: (patch: BriefEditPatch) => Promise<boolean>;
}

function toLocalDatetimeInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

type FormState = {
  title: string;
  categoryId: number | "";
  deliverableTypeIds: number[];
  prize: string;
  deadlineAt: string;
  description: string;
};

function formFromContest(contest: ContestDetail): FormState {
  return {
    title: contest.title,
    categoryId: contest.category.id,
    deliverableTypeIds: contest.deliverable_types.map((dt) => dt.id),
    prize: String(contest.prize),
    deadlineAt: toLocalDatetimeInput(contest.deadline_at),
    description: contest.description,
  };
}

export function BriefEditPanel({
  contest,
  categories,
  deliverableTypes,
  saving,
  error,
  deliverableTypesChangedNotice,
  onDismissDeliverableTypesChangedNotice,
  onSave,
}: BriefEditPanelProps) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<FormState>(() => formFromContest(contest));

  function startEditing() {
    setForm(formFromContest(contest));
    setEditing(true);
  }

  function cancelEditing() {
    setEditing(false);
  }

  function toggleDeliverableType(id: number) {
    setForm((prev) => ({
      ...prev,
      deliverableTypeIds: prev.deliverableTypeIds.includes(id)
        ? prev.deliverableTypeIds.filter((x) => x !== id)
        : [...prev.deliverableTypeIds, id],
    }));
  }

  async function submit() {
    if (form.categoryId === "") return;
    const prizeNumber = Number(form.prize);
    if (!Number.isFinite(prizeNumber) || prizeNumber <= 0) return;
    if (form.deliverableTypeIds.length === 0) return;
    if (!form.deadlineAt) return;

    const ok = await onSave({
      title: form.title.trim(),
      category_id: form.categoryId,
      deliverable_type_ids: form.deliverableTypeIds,
      prize: prizeNumber,
      deadline_at: new Date(form.deadlineAt).toISOString(),
      description: form.description,
    });
    if (ok) setEditing(false);
  }

  return (
    <section className="border-b border-rule px-8 py-5" data-testid="draft-brief-edit-panel">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold">브리프</p>
          {/* 결제 전까지는 무엇이든 고칠 수 있다는 것이 화면에서 읽혀야 한다
              (#113 AC) — 언제부터 못 고치는지 알고 결제를 누른다. */}
          <p className="text-xs text-ink/50" data-testid="draft-editable-notice">
            결제 전까지는 자유롭게 고칠 수 있습니다 — 결제가 끝나면 잠깁니다.
          </p>
        </div>
        {!editing && (
          <button
            type="button"
            onClick={startEditing}
            data-testid="draft-edit-brief-toggle"
            className="border border-rule px-3 py-1.5 text-xs hover:border-ink"
          >
            수정
          </button>
        )}
      </div>

      {deliverableTypesChangedNotice && (
        <div
          role="status"
          data-testid="draft-deliverable-types-changed-notice"
          className="mt-3 flex items-start justify-between gap-3 border border-attention/50 bg-attention/5 px-3 py-2 text-xs text-attention"
        >
          <span>
            요구형태가 바뀌었습니다 — 기존에 붙여둔 요구사항이 새 요구형태와 맞는지 검토해 주세요. 지워지지는
            않았습니다.
          </span>
          <button
            type="button"
            onClick={onDismissDeliverableTypesChangedNotice}
            data-testid="draft-deliverable-types-changed-dismiss"
            className="shrink-0 underline"
          >
            확인
          </button>
        </div>
      )}

      {!editing ? null : (
        <div className="mt-4 flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm">
            제목
            <input
              value={form.title}
              onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value }))}
              maxLength={200}
              data-testid="draft-edit-title"
              className="border border-rule bg-paper px-3 py-2"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            카테고리
            <select
              value={form.categoryId}
              onChange={(event) =>
                setForm((prev) => ({
                  ...prev,
                  categoryId: event.target.value ? Number(event.target.value) : "",
                }))
              }
              data-testid="draft-edit-category"
              className="border border-rule bg-paper px-3 py-2"
            >
              <option value="">선택해주세요</option>
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
          </label>

          <fieldset className="flex flex-col gap-2 text-sm">
            <legend className="mb-1 text-xs text-ink/60">요구형태 · 복수 선택</legend>
            {deliverableTypes.map((dt) => (
              <label
                key={dt.id}
                className="flex items-center justify-between border border-rule px-3 py-2"
                data-testid={`draft-edit-deliverable-type-${dt.id}`}
              >
                <span className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={form.deliverableTypeIds.includes(dt.id)}
                    onChange={() => toggleDeliverableType(dt.id)}
                    data-testid={`draft-edit-deliverable-type-${dt.id}-checkbox`}
                  />
                  {dt.name}
                </span>
                <span className="font-mono text-xs text-ink/60">{formatPrize(dt.minimum_prize)}</span>
              </label>
            ))}
          </fieldset>

          <label className="flex flex-col gap-1 text-sm">
            상금 (원)
            <input
              type="number"
              min={1}
              value={form.prize}
              onChange={(event) => setForm((prev) => ({ ...prev, prize: event.target.value }))}
              data-testid="draft-edit-prize"
              className="border border-rule bg-paper px-3 py-2 font-mono"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            마감 기한
            <input
              type="datetime-local"
              value={form.deadlineAt}
              onChange={(event) => setForm((prev) => ({ ...prev, deadlineAt: event.target.value }))}
              data-testid="draft-edit-deadline"
              className="border border-rule bg-paper px-3 py-2"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            설명 (선택)
            <textarea
              value={form.description}
              onChange={(event) => setForm((prev) => ({ ...prev, description: event.target.value }))}
              rows={3}
              data-testid="draft-edit-description"
              className="border border-rule bg-paper px-3 py-2"
            />
          </label>

          {error && (
            <p role="alert" data-testid="draft-edit-error" className="text-sm text-attention">
              {error}
            </p>
          )}

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void submit()}
              disabled={saving}
              data-testid="draft-edit-save"
              className="border border-ink bg-ink px-4 py-2 text-xs text-paper disabled:opacity-50"
            >
              {saving ? "저장하는 중..." : "저장"}
            </button>
            <button
              type="button"
              onClick={cancelEditing}
              disabled={saving}
              data-testid="draft-edit-cancel"
              className="border border-rule px-4 py-2 text-xs hover:border-ink disabled:opacity-50"
            >
              취소
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
