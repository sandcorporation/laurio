"use client";

// Requirement 하나에 대한 자가 응답 + Evidence 연결 (FE-10, #35).
//
// 핵심 인수조건: **Evidence가 비어 있는 필수 항목은 시각적으로 구분되고, 그대로
// 내면 미달로 채점된다는 것이 그 자리에 표시된다**(ADR-0014) — 강제로 막지는
// 않는다. 그 신호를 이 컴포넌트 하나가 책임진다.
import { EVIDENCE_KINDS, type EvidenceIn, type RequirementOut } from "@/lib/submissions/types";

export interface RequirementFieldState {
  isMet: boolean;
  note: string;
  evidence: EvidenceIn[];
}

export interface RequirementFieldProps {
  requirement: RequirementOut;
  state: RequirementFieldState;
  onChange: (next: RequirementFieldState) => void;
  disabled: boolean;
  testId: string;
}

export function RequirementField({
  requirement,
  state,
  onChange,
  disabled,
  testId,
}: RequirementFieldProps) {
  const isRequired = requirement.grade === "required";
  const isUnlinked = state.evidence.length === 0;
  const showUnmetWarning = isRequired && isUnlinked;

  function addEvidence() {
    onChange({ ...state, evidence: [...state.evidence, { kind: "screenshot", value: "" }] });
  }

  function updateEvidence(index: number, patch: Partial<EvidenceIn>) {
    const evidence = state.evidence.map((item, i) => (i === index ? { ...item, ...patch } : item));
    onChange({ ...state, evidence });
  }

  function removeEvidence(index: number) {
    onChange({ ...state, evidence: state.evidence.filter((_, i) => i !== index) });
  }

  return (
    <div
      data-testid={testId}
      data-unmet-warning={showUnmetWarning ? "true" : "false"}
      className={`flex flex-col gap-3 rounded-md border p-4 ${
        showUnmetWarning ? "border-attention" : "border-rule"
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-2">
          <span
            className={`rounded-sm border px-2 py-0.5 text-xs ${
              isRequired ? "border-attention text-attention" : "border-rule text-ink"
            }`}
          >
            {isRequired ? "필수" : "선택"}
          </span>
          <p className="text-sm">{requirement.text}</p>
        </div>
        <label className="flex shrink-0 items-center gap-1 text-sm">
          <input
            type="checkbox"
            checked={state.isMet}
            disabled={disabled}
            onChange={(event) => onChange({ ...state, isMet: event.target.checked })}
            data-testid={`${testId}-is-met`}
          />
          충족
        </label>
      </div>

      {showUnmetWarning && (
        <p role="alert" className="text-sm text-attention" data-testid={`${testId}-unmet-warning`}>
          증거가 연결되지 않았습니다 — 이대로 제출하면 이 필수 항목은 미달로 채점됩니다.
        </p>
      )}

      <textarea
        className="rounded-sm border border-rule bg-paper px-2 py-1 text-sm"
        placeholder="설명(선택)"
        value={state.note}
        disabled={disabled}
        onChange={(event) => onChange({ ...state, note: event.target.value })}
        data-testid={`${testId}-note`}
      />

      <div className="flex flex-col gap-2">
        {state.evidence.map((item, index) => (
          <div key={index} className="flex items-center gap-2">
            <select
              value={item.kind}
              disabled={disabled}
              onChange={(event) => updateEvidence(index, { kind: event.target.value })}
              data-testid={`${testId}-evidence-${index}-kind`}
              className="rounded-sm border border-rule bg-paper px-2 py-1 text-sm"
            >
              {EVIDENCE_KINDS.map((kind) => (
                <option key={kind.value} value={kind.value}>
                  {kind.label}
                </option>
              ))}
            </select>
            <input
              className="flex-1 rounded-sm border border-rule bg-paper px-2 py-1 text-sm"
              placeholder="예: 01:23, screenshots/1.png, /checkout, src/api/pay.ts"
              value={item.value}
              disabled={disabled}
              onChange={(event) => updateEvidence(index, { value: event.target.value })}
              data-testid={`${testId}-evidence-${index}-value`}
            />
            <button
              type="button"
              disabled={disabled}
              onClick={() => removeEvidence(index)}
              data-testid={`${testId}-evidence-${index}-remove`}
              className="rounded-sm border border-rule px-2 py-1 text-xs hover:border-ink"
            >
              삭제
            </button>
          </div>
        ))}
        <button
          type="button"
          disabled={disabled}
          onClick={addEvidence}
          data-testid={`${testId}-add-evidence`}
          className="w-fit rounded-sm border border-rule px-2 py-1 text-xs hover:border-ink"
        >
          + 증거 추가
        </button>
      </div>
    </div>
  );
}
