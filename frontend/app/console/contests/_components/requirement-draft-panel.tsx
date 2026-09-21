"use client";

// 공모전 초안 패널 — 오른쪽 컬럼 (FE-12, #37, design/Brief.dc.html).
//
// 제목·요구형태·상금은 왼쪽의 `BriefEditPanel`이 고친다(#113) — 이 패널은
// 그 값들을 그대로 보여주기만 한다. 이 패널이 직접 다루는 것은 Requirement
// 체크리스트 CRUD뿐이다 — AI는 제안하고 Sponsor가 최종 결정한다. 아래
// 발행 자리(공개하기/결제하러 가기/제출 중 안내)만 `contest.status`로
// 갈린다(#473, ADR-0051).
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
  // 개최자 표시 이름(#447) — 비어 있으면 공개(무료)·결제 시작(유료)이 422로
  // 거절되므로, 공개 버튼 앞에서 그 자리에 채우게 한다. 저장은 기존 프로필
  // 저장 API(`POST /accounts/sponsor-profile`)를 그대로 쓴다.
  onSaveSponsorDisplayName?: (name: string) => Promise<boolean>;
  savingSponsorDisplayName?: boolean;
  sponsorDisplayNameError?: string | null;
}

function SponsorDisplayNameGate({
  displayName,
  onSave,
  saving,
  error,
}: {
  displayName: string | null;
  onSave?: (name: string) => Promise<boolean>;
  saving?: boolean;
  error?: string | null;
}) {
  const [input, setInput] = useState("");

  if (displayName) {
    return (
      <p className="text-xs text-ink/60" data-testid="grill-sponsor-display-name">
        개최자 표시 이름 · <span className="font-medium text-ink">{displayName}</span>
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2" data-testid="grill-sponsor-display-name-gate">
      <p className="text-xs leading-relaxed text-ink/60">
        공개하려면 참가자에게 보일 개최자 표시 이름이 필요합니다.
      </p>
      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          maxLength={100}
          placeholder="개최자 표시 이름"
          data-testid="grill-sponsor-display-name-input"
          className={`flex-1 ${INPUT_CLASS}`}
        />
        <button
          type="button"
          disabled={saving || !input.trim() || !onSave}
          onClick={() => void onSave?.(input.trim())}
          data-testid="grill-sponsor-display-name-save"
          className={buttonClass("secondary", "sm")}
        >
          {saving ? "저장 중..." : "저장"}
        </button>
      </div>
      {error && (
        <ErrorNote>
          <span data-testid="grill-sponsor-display-name-error">{error}</span>
        </ErrorNote>
      )}
    </div>
  );
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
  onSaveSponsorDisplayName,
  savingSponsorDisplayName = false,
  sponsorDisplayNameError = null,
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
      {/* **머리말이 지금 상태를 말한다**(#473 후속). 공개된 뒤에도 이 패널이
          열리게 되면서(ADR-0051) published 인 공모전에 「공모전 초안 · 임시
          저장됨」이라고 적히는 일이 생겼다 — 이미 공개돼 참가자가 보고 있는
          공모전을 초안이라 부르면 개최자가 자기가 무엇을 고치는 중인지 잘못
          안다. */}
      <div className="flex items-center justify-between border-b border-rule px-7 py-5">
        <p className="text-sm font-semibold">
          {contest.status === "draft" ? "공모전 초안" : "공개된 공모전"}
        </p>
        <p className="text-xs text-ink/50" data-testid="grill-draft-autosaved">
          {contest.status === "draft" ? "임시 저장됨" : "제출 받는 중"}
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
              {contest.status === "draft"
                ? "아직 체크리스트가 없습니다 — AI와 대화하거나 직접 추가해 보세요."
                : "아직 체크리스트가 없습니다 — 직접 추가해 보세요."}
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
        {contest.status === "draft" ? (
          <>
            <SponsorDisplayNameGate
              displayName={contest.sponsor_display_name ?? null}
              onSave={onSaveSponsorDisplayName}
              saving={savingSponsorDisplayName}
              error={sponsorDisplayNameError}
            />
            {contest.is_free ? (
              <>
                <p
                  className="text-center text-xs leading-relaxed text-ink/50"
                  data-testid="grill-free-publish-notice"
                >
                  {requirements.length === 0
                    ? "요구사항을 하나 이상 적어야 공개할 수 있습니다"
                    : !contest.sponsor_display_name
                      ? "개최자 표시 이름을 먼저 등록해야 공개할 수 있습니다"
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
                  disabled={
                    publishing || !onPublish || requirements.length === 0 || !contest.sponsor_display_name
                  }
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
          </>
        ) : (
          // published — 제출을 받는 동안이다(#473, ADR-0051). 공개·결제
          // 자리는 이미 지났으니 대신 공개 상세로 이어간다.
          <>
            <p
              className="text-center text-xs leading-relaxed text-ink/50"
              data-testid="grill-published-notice"
            >
              제출을 받고 있습니다 — 마감 전까지 계속 고칠 수 있습니다.
            </p>
            <Link
              href={`/contests/${contest.id}`}
              data-testid="grill-view-published-contest"
              className="mt-1 block text-center text-xs font-semibold underline"
            >
              공모전 보기
            </Link>
          </>
        )}
      </div>
    </aside>
  );
}
