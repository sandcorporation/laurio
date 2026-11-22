"use client";

import { useState } from "react";

import { ErrorNote, FieldLabel, INPUT_CLASS } from "@/app/components/ui";
import { updateClass, type ClassRow, type GradingMethod } from "@/lib/classes/api";
import { UNAVAILABLE_TOOLTIP, vendorLabel } from "@/lib/classes/grading-cost";

import { ScoringCalculator } from "./scoring-calculator";

type Field = "scoring_method" | "quality_method";

const ROWS: { field: Field; label: string; testId: string }[] = [
  { field: "scoring_method", label: "채점 방식", testId: "scoring-method" },
  { field: "quality_method", label: "완성도 검사 방식", testId: "quality-method" },
];

export const METHOD_LABEL: Record<GradingMethod, string> = { single: "한 번 호출", agent: "에이전트" };

const ESCALATION_STAGED_OFF = "근거 인용 채점이 꺼져 있음";

export function GradingMethodSection({ classId, classroom, onSaved }: { classId: number; classroom: ClassRow; onSaved: () => void }) {
  const [saving, setSaving] = useState<Field | null>(null);
  const [error, setError] = useState<string | null>(null);
  const vendor = vendorLabel(classroom.scoring_connection_kind);

  async function choose(field: Field, value: GradingMethod) {
    if (classroom[field] === value) return;
    setSaving(field);
    setError(null);
    const result = await updateClass(classId, { [field]: value });
    if (result.ok) onSaved();
    else setError(result.detail);
    setSaving(null);
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      {ROWS.map(({ field, label, testId }) => (
        <div key={field} className="flex flex-col gap-1.5" data-testid={testId}>
          <FieldLabel>{label}</FieldLabel>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <div role="radiogroup" aria-label={label} className="inline-flex border border-rule">
              {classroom.grading_method_options.map((option) => {
                const checked = classroom[field] === option.value;
                const reason = option.unavailable_reason ? UNAVAILABLE_TOOLTIP[option.unavailable_reason] : undefined;
                return (
                  <button
                    key={option.value}
                    type="button"
                    role="radio"
                    aria-checked={checked}
                    data-testid={`${testId}-${option.value}`}
                    disabled={!option.selectable || saving !== null}
                    title={option.selectable ? undefined : reason}
                    onClick={() => void choose(field, option.value)}
                    className={`px-3 py-1.5 text-[13px] disabled:cursor-not-allowed ${
                      checked ? "bg-ink text-surface" : "bg-surface text-ink disabled:text-ink/35"
                    }`}
                  >
                    {METHOD_LABEL[option.value]}
                  </button>
                );
              })}
            </div>
            {vendor ? (
              <span data-testid={`${testId}-vendor`} className="text-[13px] text-ink/60">
                {vendor}
              </span>
            ) : null}
          </div>
        </div>
      ))}
      <EscalationModelField classId={classId} classroom={classroom} onSaved={onSaved} onError={setError} />
      {error ? (
        <ErrorNote>
          <span data-testid="grading-method-error">{error}</span>
        </ErrorNote>
      ) : null}
      <div className="border-t border-rule pt-4">
        <ScoringCalculator
          key={calculatorKey(classroom)}
          classId={classId}
        />
      </div>
    </div>
  );
}

// 키 저장·연결·방식·기본 모델이 바뀌면 계산기를 처음 값(지금 이 클래스의 조합)부터 다시 받는다.
function calculatorKey(classroom: ClassRow): string {
  return [
    classroom.scoring_connection_kind,
    classroom.openai_key ? "openai" : "",
    classroom.anthropic_key ? "anthropic" : "",
    classroom.scoring_method,
    classroom.default_model,
    classroom.escalation_model,
  ].join(":");
}

// 의심 재판정 모델(#1291) — 고르면 곧바로 저장한다(방식 칸과 같은 모양). staged 가 꺼져 있거나 고를 모델이 없으면 막는다.
function EscalationModelField({
  classId,
  classroom,
  onSaved,
  onError,
}: {
  classId: number;
  classroom: ClassRow;
  onSaved: () => void;
  onError: (message: string | null) => void;
}) {
  const [saving, setSaving] = useState(false);
  const options = classroom.escalation_model_options;
  const disabledReason = !classroom.staged_scoring
    ? ESCALATION_STAGED_OFF
    : options.length === 0
      ? UNAVAILABLE_TOOLTIP.compatible_server
      : undefined;
  // 저장해 둔 모델이 지금 연결의 목록에 없으면(연결을 바꿨다) 그 값도 선택지에 남겨 무엇이 저장됐는지 보인다.
  const shown =
    classroom.escalation_model && !options.includes(classroom.escalation_model)
      ? [classroom.escalation_model, ...options]
      : options;

  async function choose(value: string) {
    if (value === classroom.escalation_model) return;
    setSaving(true);
    onError(null);
    const result = await updateClass(classId, { escalation_model: value });
    if (result.ok) onSaved();
    else onError(result.detail);
    setSaving(false);
  }

  return (
    <div className="flex flex-col gap-1.5" data-testid="escalation-model">
      <label htmlFor="escalation-model-select">
        <FieldLabel>의심 재판정 모델</FieldLabel>
      </label>
      <select
        id="escalation-model-select"
        data-testid="escalation-model-select"
        value={classroom.escalation_model}
        disabled={disabledReason !== undefined || saving}
        title={disabledReason}
        onChange={(event) => void choose(event.target.value)}
        className={`${INPUT_CLASS} max-w-[280px] font-mono disabled:cursor-not-allowed disabled:text-ink/35`}
      >
        <option value="">끔</option>
        {shown.map((model) => (
          <option key={model} value={model}>
            {model}
          </option>
        ))}
      </select>
    </div>
  );
}
