"use client";

// 브리프 수정 패널 (#113, 부모 #110; 제출을 받는 동안의 편집은 #473, ADR-0051).
//
// DRAFT는 결제가 문을 닫기 전까지, PUBLISHED는 마감이 문을 닫기 전까지 제목·
// 설명·카테고리·요구형태·마감을 고칠 수 있다. 이 컴포넌트는 순전히 폼이다 —
// 저장이 실제로 무엇을 바꾸는지(파생값 재계산 포함)는 전부 백엔드(`PATCH
// /contests/{id}`)가 판정한다. 이 화면은 그 결과를 그대로 받아 부모(draft/
// page.tsx)에게 새 Contest를 돌려줄 뿐, 최소 상금이나 미달 여부를 스스로
// 계산하지 않는다(#113 AC — "판정은 백엔드가 한다").
//
// **상금은 PUBLISHED에서는 애초에 칸을 그리지 않는다** — 무료 공모전이 상금
// 칸을 감추는 것과 같은 이유(사고 예방)다: 이미 결제·Escrow가 확정한 금액이라
// 백엔드도 이 상태에서는 `prize`가 오면 422로 거절한다.
import { useState } from "react";

import { DescriptionField } from "@/app/components/description-field";
import { ErrorNote, INPUT_CLASS, buttonClass } from "@/app/components/ui";
import { formatPrize } from "@/lib/contest-format";
import { checkPublicTextForBannedWords } from "@/lib/contests/banned-words-check";
import type { Category, ContestDetail, DeliverableType } from "@/lib/contests/grill-types";

import { ClassroomImportField } from "./classroom-import-field";

export type BriefEditPatch = {
  title: string;
  category_id: number;
  deliverable_type_ids: number[];
  require_demo_video: boolean;
  require_screenshot: boolean;
  // 무료 공모전(#415, ADR-0048)은 상금 자체가 없다 — `prize`를 아예 보내지
  // 않는다(백엔드도 무료 공모전에 `prize`가 실리면 422로 거절한다).
  prize?: number;
  deadline_at: string;
  description: string;
  // 「클래스에서 들여오기」 허용(#547, ADR-0054) — 무료 공모전만 보낸다(유료는 백엔드가 422).
  allows_classroom_import?: boolean;
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
  requireDemoVideo: boolean;
  requireScreenshot: boolean;
  prize: string;
  deadlineAt: string;
  description: string;
  allowsClassroomImport: boolean;
};

function formFromContest(contest: ContestDetail): FormState {
  return {
    title: contest.title,
    categoryId: contest.category.id,
    deliverableTypeIds: contest.deliverable_types.map((dt) => dt.id),
    requireDemoVideo: contest.require_demo_video,
    requireScreenshot: contest.require_screenshot,
    prize: String(contest.prize),
    deadlineAt: toLocalDatetimeInput(contest.deadline_at),
    description: contest.description,
    allowsClassroomImport: contest.allows_classroom_import ?? false,
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
  // 저장을 막는 이유(빈 카테고리·상금·요구형태·마감) — 서버 오류(`error` prop)와
  // 갈라 둔다. 예전에는 이 네 가지 중 하나라도 걸리면 `submit()`이 아무 것도
  // 하지 않고 조용히 리턴해, Sponsor가 저장을 눌러도 클릭이 씹힌 것처럼
  // 보였다(코드리뷰 지적). 지금은 버튼도 막고(아래 `formInvalidReason`) 그
  // 이유를 화면에 남긴다 — 이중 방어다.
  const [validationError, setValidationError] = useState<string | null>(null);

  function startEditing() {
    setForm(formFromContest(contest));
    setValidationError(null);
    setEditing(true);
  }

  function cancelEditing() {
    setValidationError(null);
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

  // PUBLISHED에서는 상금 칸 자체를 그리지 않는다(아래) — 결제·Escrow가 이미
  // 확정한 금액이라 이 폼이 다시 열 대상이 아니다.
  const isDraft = contest.status === "draft";
  const canEditPrize = isDraft && !contest.is_free;
  const prizeNumber = Number(form.prize);
  const formInvalidReason =
    form.categoryId === ""
      ? "카테고리를 선택해주세요."
      : canEditPrize && (!Number.isFinite(prizeNumber) || prizeNumber <= 0)
        ? "상금은 0보다 큰 금액이어야 합니다."
        : form.deliverableTypeIds.length === 0
          ? "요구형태를 하나 이상 선택해주세요."
          : !form.deadlineAt
            ? "마감 기한을 선택해주세요."
            : null;

  async function submit() {
    // `form.categoryId === ""`도 formInvalidReason이 이미 잡아내지만, TS는 그
    // 바깥 변수로부터 `form.categoryId`의 타입을 좁히지 못한다 — 아래
    // `category_id: form.categoryId`가 `number`를 요구하므로 여기서 한 번 더
    // 좁힌다(formInvalidReason이 null이면 항상 참이라 실질적으로는 도달하지
    // 않는 분기다).
    if (formInvalidReason || form.categoryId === "") {
      // 버튼이 막혀 있는 게 정상 경로지만, 값이 프로그램적으로(테스트 등)
      // 바뀌어 버튼 disabled 판정과 어긋나는 순간에도 조용히 아무 일도 안
      // 하지 않는다 — 왜 저장되지 않았는지를 반드시 알린다.
      setValidationError(formInvalidReason ?? "카테고리를 선택해주세요.");
      return;
    }
    // 제출을 누르는 순간에만 검사한다(spec #474, #479) — 서버가 진짜 문이다.
    const titleBannedWordMessage = checkPublicTextForBannedWords(form.title.trim(), "제목");
    if (titleBannedWordMessage) {
      setValidationError(titleBannedWordMessage);
      return;
    }
    const descriptionBannedWordMessage = checkPublicTextForBannedWords(form.description, "설명");
    if (descriptionBannedWordMessage) {
      setValidationError(descriptionBannedWordMessage);
      return;
    }
    setValidationError(null);

    const ok = await onSave({
      title: form.title.trim(),
      category_id: form.categoryId,
      deliverable_type_ids: form.deliverableTypeIds,
      require_demo_video: form.requireDemoVideo,
      require_screenshot: form.requireScreenshot,
      ...(canEditPrize ? { prize: prizeNumber } : {}),
      deadline_at: new Date(form.deadlineAt).toISOString(),
      description: form.description,
      ...(contest.is_free ? { allows_classroom_import: form.allowsClassroomImport } : {}),
    });
    if (ok) setEditing(false);
  }

  return (
    <section className="border-b border-rule px-8 py-5" data-testid="draft-brief-edit-panel">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold">브리프</p>
          {/* 언제까지 고칠 수 있는지가 화면에서 읽혀야 한다(#113 AC, #473) —
              DRAFT는 결제가, PUBLISHED는 마감이 문을 닫는다. */}
          <p className="text-xs text-ink/50" data-testid="draft-editable-notice">
            {isDraft
              ? "마감 전까지는 자유롭게 고칠 수 있습니다 — 결제 뒤에도 계속 고칠 수 있습니다."
              : "마감 전까지는 자유롭게 고칠 수 있습니다 — 이미 제출한 참가자에게는 바뀐 내용이 알림으로 갑니다."}
          </p>
        </div>
        {!editing && (
          <button
            type="button"
            onClick={startEditing}
            data-testid="draft-edit-brief-toggle"
            className={buttonClass("secondary", "sm")}
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
              className={INPUT_CLASS}
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
              className={INPUT_CLASS}
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
          <div className="mt-3 flex flex-col gap-2 text-sm">
            <label className="flex items-center gap-2"><input type="checkbox" checked={form.requireDemoVideo} onChange={(e) => setForm((p) => ({ ...p, requireDemoVideo: e.target.checked }))} />시연 영상 제출 필수</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={form.requireScreenshot} onChange={(e) => setForm((p) => ({ ...p, requireScreenshot: e.target.checked }))} />스크린샷 제출 필수</label>
          </div>
          </fieldset>

          {canEditPrize && (
            <label className="flex flex-col gap-1 text-sm">
              상금 (원)
              <input
                type="number"
                min={1}
                value={form.prize}
                onChange={(event) => setForm((prev) => ({ ...prev, prize: event.target.value }))}
                data-testid="draft-edit-prize"
                className={`${INPUT_CLASS} font-mono`}
              />
            </label>
          )}

          <label className="flex flex-col gap-1 text-sm">
            마감 기한
            <input
              type="datetime-local"
              value={form.deadlineAt}
              min={toLocalDatetimeInput(new Date().toISOString())}
              onChange={(event) => setForm((prev) => ({ ...prev, deadlineAt: event.target.value }))}
              data-testid="draft-edit-deadline"
              className={INPUT_CLASS}
            />
          </label>

          {contest.is_free && (
            <ClassroomImportField
              checked={form.allowsClassroomImport}
              onChange={(next) => setForm((prev) => ({ ...prev, allowsClassroomImport: next }))}
              testId="draft-edit-classroom-import"
            />
          )}

          <DescriptionField
            label="설명 (선택)"
            value={form.description}
            onChange={(next) => setForm((prev) => ({ ...prev, description: next }))}
            title={form.title}
            testId="draft-edit-description"
          />

          {(validationError || error) && (
            <ErrorNote>
              <span data-testid="draft-edit-error">{validationError || error}</span>
            </ErrorNote>
          )}

          {/* 제출을 시도하기 전에도 왜 저장 버튼이 막혀 있는지 보인다 — 버튼만
              비활성화하고 이유를 말하지 않으면 눌러도 안 눌러도 똑같이
              「아무 반응 없음」으로 보인다(코드리뷰 지적). */}
          {!validationError && formInvalidReason && (
            <p className="text-xs text-ink/50" data-testid="draft-edit-validation-hint">
              {formInvalidReason}
            </p>
          )}

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void submit()}
              disabled={saving || !!formInvalidReason}
              data-testid="draft-edit-save"
              className={buttonClass("primary", "sm")}
            >
              {saving ? "저장하는 중..." : "저장"}
            </button>
            <button
              type="button"
              onClick={cancelEditing}
              disabled={saving}
              data-testid="draft-edit-cancel"
              className={buttonClass("secondary", "sm")}
            >
              취소
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
