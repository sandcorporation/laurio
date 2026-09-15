"use client";

// 공모전 초안 패널 — 오른쪽 컬럼 (FE-12, #37, design/Brief.dc.html).
//
// 제목·요구형태·상금은 Contest 생성 시점(POST /api/contests)에 이미 확정되어
// 있다 — 백엔드에 Contest 필드를 고치는 엔드포인트가 없으므로 여기서는 그
// 값들을 그대로 보여주기만 한다(REQUEST.md "관통 원칙"과 별개로, 이건 단지
// 이 API 표면의 현재 범위다). 실제로 이 화면에서 계속 바뀌는 것은
// Requirement 체크리스트뿐이고, 그 CRUD가 이 패널의 핵심이다 — AI는 제안하고
// Sponsor가 최종 결정한다.
import { useState } from "react";
import Link from "next/link";

import { ErrorNote, INPUT_CLASS, buttonClass } from "@/app/components/ui";
import { formatPrize } from "@/lib/contest-format";
import type { ContestDetail, RequirementGrade, RequirementOut } from "@/lib/contests/grill-types";
import { REQUIREMENT_GRADES, REQUIREMENT_TEXT_MAX_LENGTH } from "@/lib/contests/grill-types";

export interface RequirementDraftPanelProps {
  contest: ContestDetail;
  requirements: RequirementOut[];
  requirementError: string | null;
  requirementBusy: boolean;
  onAdd: (text: string, grade: RequirementGrade) => Promise<void>;
  onUpdate: (id: number, patch: { text?: string; grade?: RequirementGrade }) => Promise<boolean>;
  onDelete: (id: number) => Promise<void>;
  // 무료 공모전(#415, ADR-0048) 전용 — `contest.is_free`가 true일 때만 쓰인다.
  // 결제 안내·링크 대신 이 자리에 공개 버튼을 그린다(본인확인·결제 없이
  // 개최 권한만으로 공개한다).
  onPublish?: () => Promise<void>;
  publishing?: boolean;
  publishError?: string | null;
}

function RequirementRow({
  requirement,
  busy,
  onUpdate,
  onDelete,
}: {
  requirement: RequirementOut;
  busy: boolean;
  onUpdate: (id: number, patch: { text?: string; grade?: RequirementGrade }) => Promise<boolean>;
  onDelete: (id: number) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(requirement.text);
  const [grade, setGrade] = useState<RequirementGrade>(requirement.grade as RequirementGrade);

  async function save() {
    const trimmed = text.trim();
    if (!trimmed) return;
    const ok = await onUpdate(requirement.id, { text: trimmed, grade });
    if (ok) setEditing(false);
  }

  if (editing) {
    return (
      <div
        className="flex flex-col gap-2 border-t border-rule px-6 py-3"
        data-testid={`requirement-row-${requirement.id}`}
      >
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          maxLength={REQUIREMENT_TEXT_MAX_LENGTH}
          rows={2}
          data-testid={`requirement-row-${requirement.id}-edit-text`}
          className={`resize-none ${INPUT_CLASS}`}
        />
        <div className="flex items-center gap-2">
          <select
            value={grade}
            onChange={(event) => setGrade(event.target.value as RequirementGrade)}
            data-testid={`requirement-row-${requirement.id}-edit-grade`}
            className={INPUT_CLASS}
          >
            {REQUIREMENT_GRADES.map((g) => (
              <option key={g.value} value={g.value}>
                {g.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={busy || !text.trim()}
            onClick={() => void save()}
            data-testid={`requirement-row-${requirement.id}-save`}
            className={buttonClass("primary", "sm")}
          >
            저장
          </button>
          <button
            type="button"
            onClick={() => {
              setText(requirement.text);
              setGrade(requirement.grade as RequirementGrade);
              setEditing(false);
            }}
            data-testid={`requirement-row-${requirement.id}-cancel`}
            className={buttonClass("secondary", "sm")}
          >
            취소
          </button>
        </div>
      </div>
    );
  }

  const isRequired = requirement.grade === "required";
  return (
    <div
      className="flex items-start gap-3 border-t border-rule px-6 py-3"
      data-testid={`requirement-row-${requirement.id}`}
    >
      <span
        className={`shrink-0 pt-0.5 text-[10.5px] font-semibold ${
          isRequired ? "text-attention" : "text-ink/60"
        }`}
      >
        {isRequired ? "필수" : "선택"}
      </span>
      <span className="flex-1 text-sm leading-relaxed" data-testid={`requirement-row-${requirement.id}-text`}>
        {requirement.text}
      </span>
      <div className="flex shrink-0 gap-2">
        <button
          type="button"
          onClick={() => setEditing(true)}
          data-testid={`requirement-row-${requirement.id}-edit`}
          className="text-xs text-ink/60 hover:text-ink"
        >
          수정
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void onDelete(requirement.id)}
          data-testid={`requirement-row-${requirement.id}-delete`}
          className="text-xs text-attention hover:opacity-70"
        >
          삭제
        </button>
      </div>
    </div>
  );
}

export function RequirementDraftPanel({
  contest,
  requirements,
  requirementError,
  requirementBusy,
  onAdd,
  onUpdate,
  onDelete,
  onPublish,
  publishing = false,
  publishError = null,
}: RequirementDraftPanelProps) {
  const [manualOpen, setManualOpen] = useState(false);
  const [manualText, setManualText] = useState("");
  const [manualGrade, setManualGrade] = useState<RequirementGrade>("required");

  const requiredCount = requirements.filter((r) => r.grade === "required").length;
  const optionalCount = requirements.length - requiredCount;

  async function submitManual() {
    const trimmed = manualText.trim();
    if (!trimmed) return;
    await onAdd(trimmed, manualGrade);
    setManualText("");
    setManualGrade("required");
    setManualOpen(false);
  }

  return (
    <aside className="flex flex-col bg-surface" data-testid="grill-draft-panel">
      <div className="flex items-center justify-between border-b border-rule px-7 py-5">
        <p className="text-sm font-semibold">공모전 초안</p>
        <p className="text-xs text-ink/50" data-testid="grill-draft-autosaved">
          임시 저장됨
        </p>
      </div>

      <div className="flex flex-col gap-5 border-b border-rule px-7 py-5">
        <div className="flex flex-col gap-1">
          <p className="text-[11px] tracking-wide text-ink/50">제목</p>
          <p className="text-[15px] font-medium leading-snug" data-testid="grill-draft-title">
            {contest.title}
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <p className="text-[11px] tracking-wide text-ink/50">요구형태 · 복수 선택</p>
          <div className="flex flex-col gap-1.5" data-testid="grill-draft-deliverable-types">
            {contest.deliverable_types.map((dt) => (
              <div
                key={dt.id}
                className="flex items-center justify-between border border-ink px-3 py-2 text-[13.5px]"
              >
                <span>{dt.name}</span>
                <span className="font-mono text-xs text-ink/60">{formatPrize(dt.minimum_prize)}</span>
              </div>
            ))}
            <div className="flex items-center justify-between border-t border-rule px-3 pt-2 text-xs">
              <span className="text-ink/60">최소 제안 상금 합계</span>
              <span className="font-mono font-semibold" data-testid="grill-draft-minimum-total">
                {formatPrize(contest.required_minimum_prize)}
              </span>
            </div>
          </div>
        </div>

        {!contest.is_free && (
          <div className="flex flex-col gap-2">
            <p className="text-[11px] tracking-wide text-ink/50">상금</p>
            <div
              className={`flex items-center justify-between border px-3 py-2.5 ${
                contest.is_underfunded ? "border-attention" : "border-rule"
              }`}
            >
              <span className="font-mono text-lg font-semibold" data-testid="grill-draft-prize">
                {formatPrize(contest.prize)}
              </span>
              <span className="text-xs text-ink/50">원</span>
            </div>
            {contest.is_underfunded && (
              <p
                role="status"
                data-testid="grill-underfunded-badge"
                className="flex items-start gap-2 text-xs leading-relaxed text-attention"
              >
                <span>
                  합계보다{" "}
                  <strong className="font-mono font-semibold">
                    {formatPrize(contest.required_minimum_prize - contest.prize)}
                  </strong>
                  원 적어 목록에 「상금미달」 배지가 붙습니다. 그래도 개최할 수 있습니다.
                </span>
              </p>
            )}
          </div>
        )}
      </div>

      <div className="flex flex-1 flex-col overflow-y-auto">
        <div className="flex items-center justify-between px-7 py-3">
          <p className="text-[11px] tracking-wide text-ink/50">요구사항 체크리스트</p>
          <p className="font-mono text-xs text-ink/60" data-testid="grill-requirement-counts">
            필수 {requiredCount} · 선택 {optionalCount}
          </p>
        </div>

        {requirementError && (
          <div className="px-7 pb-2">
            <ErrorNote>
              <span data-testid="grill-requirement-error">{requirementError}</span>
            </ErrorNote>
          </div>
        )}

        <div data-testid="grill-requirement-list">
          {requirements.length === 0 && (
            <p className="border-t border-rule px-7 py-4 text-sm text-ink/50" data-testid="grill-requirement-empty">
              아직 체크리스트가 없습니다 — AI와 대화하거나 직접 추가해 보세요.
            </p>
          )}
          {requirements.map((requirement) => (
            <RequirementRow
              key={requirement.id}
              requirement={requirement}
              busy={requirementBusy}
              onUpdate={onUpdate}
              onDelete={onDelete}
            />
          ))}
        </div>

        <div className="border-t border-rule px-7 py-3">
          {manualOpen ? (
            <div className="flex flex-col gap-2">
              <textarea
                value={manualText}
                onChange={(event) => setManualText(event.target.value)}
                maxLength={REQUIREMENT_TEXT_MAX_LENGTH}
                rows={2}
                placeholder="검증 가능한 요구사항을 적어주세요"
                data-testid="grill-manual-add-text"
                className={`resize-none ${INPUT_CLASS}`}
              />
              <div className="flex items-center gap-2">
                <select
                  value={manualGrade}
                  onChange={(event) => setManualGrade(event.target.value as RequirementGrade)}
                  data-testid="grill-manual-add-grade"
                  className={INPUT_CLASS}
                >
                  {REQUIREMENT_GRADES.map((g) => (
                    <option key={g.value} value={g.value}>
                      {g.label}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  disabled={requirementBusy || !manualText.trim()}
                  onClick={() => void submitManual()}
                  data-testid="grill-manual-add-submit"
                  className={buttonClass("primary", "sm")}
                >
                  추가
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setManualOpen(false);
                    setManualText("");
                  }}
                  data-testid="grill-manual-add-cancel"
                  className={buttonClass("secondary", "sm")}
                >
                  취소
                </button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setManualOpen(true)}
              data-testid="grill-manual-add-open"
              className="flex items-center gap-1.5 text-xs text-ink/60 hover:text-ink"
            >
              + 직접 추가
            </button>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-2 border-t border-rule px-7 py-5">
        {contest.is_free ? (
          <>
            <p
              className="text-center text-xs leading-relaxed text-ink/50"
              data-testid="grill-free-publish-notice"
            >
              {requirements.length === 0
                ? "요구사항을 하나 이상 적어야 공개할 수 있습니다"
                : "본인확인·결제 없이 바로 공개됩니다"}
            </p>
            {publishError && (
              <ErrorNote>
                <span data-testid="grill-free-publish-error">{publishError}</span>
              </ErrorNote>
            )}
            <button
              type="button"
              onClick={() => void onPublish?.()}
              disabled={publishing || !onPublish || requirements.length === 0}
              data-testid="grill-publish-free-contest"
              className={`mt-1 ${buttonClass("primary", "sm")}`}
            >
              {publishing ? "공개하는 중..." : "공개하기"}
            </button>
          </>
        ) : (
          <>
            <p
              className="text-center text-xs leading-relaxed text-ink/50"
              data-testid="grill-payment-required-notice"
            >
              결제가 끝나야 공모전이 공개됩니다
            </p>
            {/* URL을 직접 쳐야만 결제로 닿는 경로가 되지 않도록(#86), 초안을 만든
                바로 그 자리에서 결제 화면으로 이어간다. */}
            <Link
              href={`/console/contests/${contest.id}/payment`}
              data-testid="grill-go-to-payment"
              className="mt-1 block text-center text-xs font-semibold underline"
            >
              결제하러 가기
            </Link>
          </>
        )}
      </div>
    </aside>
  );
}
