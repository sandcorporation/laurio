"use client";

// Requirement 하나에 대한 자가 응답 + 확인 위치(Evidence) (FE-10, #35).
//
// 확인 위치는 제출자가 개최자에게 「이 항목은 여기서 보세요」라고 알려 주는 선택
// 안내다 — AI 판정·완성도의 입력이 아니다(#909, ADR-0074). 그래서 비어 있어도
// 경고하지 않는다.
//
// 자료가 여럿이 된 뒤(#190, ADR-0027)로는 "데모 내 경로" 같은 확인 위치가 어느
// 자료를 가리키는지도 고를 수 있다(`EvidenceIn.asset_id`, #192) — 그러지
// 않으면 데모가 둘일 때 개최자가 어느 것의 경로인지 알 수 없다. 이 화면이
// 고를 수 있게 해 주는 목록은 **이미 저장된** 자료뿐이다(`assets` prop) — 이
// 폼에서 방금 추가한 자료는 저장 전까지 id 가 없어 가리킬 대상 자체가 없다.
import { requirementGradeLabel } from "@/lib/contests/grill-types";
import { Badge, INPUT_CLASS, buttonClass } from "@/app/components/ui";
import { ASSET_KIND_LABELS, EVIDENCE_KINDS, type EvidenceIn, type RequirementOut } from "@/lib/submissions/types";

export interface RequirementFieldState {
  isMet: boolean;
  note: string;
  evidence: EvidenceIn[];
}

export interface RequirementFieldAssetOption {
  id: number;
  kind: string;
  label: string;
  value: string;
}

export interface RequirementFieldProps {
  requirement: RequirementOut;
  state: RequirementFieldState;
  onChange: (next: RequirementFieldState) => void;
  disabled: boolean;
  testId: string;
  /** 확인 위치가 가리킬 수 있는, 이미 저장된 자료 목록. */
  assets: RequirementFieldAssetOption[];
}

export function RequirementField({
  requirement,
  state,
  onChange,
  disabled,
  testId,
  assets,
}: RequirementFieldProps) {
  const isRequired = requirement.grade === "required";

  function addEvidence() {
    onChange({
      ...state,
      evidence: [...state.evidence, { kind: "screenshot", value: "", asset_id: null }],
    });
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
      className="flex flex-col gap-3 border border-rule p-4"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-2">
          <Badge tone={isRequired ? "attention" : "neutral"}>{requirementGradeLabel(requirement.grade)}</Badge>
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

      <textarea
        className={INPUT_CLASS}
        placeholder="설명(선택)"
        value={state.note}
        disabled={disabled}
        onChange={(event) => onChange({ ...state, note: event.target.value })}
        data-testid={`${testId}-note`}
      />

      <div className="flex flex-col gap-2">
        <p className="text-xs font-semibold">확인 위치(선택)</p>
        {state.evidence.map((item, index) => (
          <div key={index} className="flex flex-wrap items-center gap-2">
            <select
              value={item.kind}
              disabled={disabled}
              onChange={(event) => updateEvidence(index, { kind: event.target.value })}
              data-testid={`${testId}-evidence-${index}-kind`}
              className={INPUT_CLASS}
            >
              {EVIDENCE_KINDS.map((kind) => (
                <option key={kind.value} value={kind.value}>
                  {kind.label}
                </option>
              ))}
            </select>
            <select
              value={item.asset_id != null ? String(item.asset_id) : ""}
              disabled={disabled}
              onChange={(event) =>
                updateEvidence(index, {
                  asset_id: event.target.value === "" ? null : Number(event.target.value),
                })
              }
              data-testid={`${testId}-evidence-${index}-asset`}
              className={INPUT_CLASS}
            >
              <option value="">어느 자료에서 볼 수 있는지 (선택 안 함)</option>
              {assets.map((asset) => (
                <option key={asset.id} value={asset.id}>
                  {ASSET_KIND_LABELS[asset.kind] ?? asset.kind}: {asset.label || asset.value}
                </option>
              ))}
            </select>
            <input
              className={`flex-1 ${INPUT_CLASS}`}
              placeholder="예: 01:23, screenshots/1.png, /checkout, accounts/views.py 의 signup()"
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
              className={buttonClass("secondary", "sm")}
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
          className={buttonClass("secondary", "sm")}
        >
          + 확인 위치 추가
        </button>
      </div>
    </div>
  );
}
