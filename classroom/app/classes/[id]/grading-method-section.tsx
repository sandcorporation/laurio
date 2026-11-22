"use client";

import { useState } from "react";

import { ErrorNote, FieldLabel } from "@/app/components/ui";
import { updateClass, type ClassRow, type GradingMethod } from "@/lib/classes/api";
import { UNAVAILABLE_TOOLTIP, vendorLabel } from "@/lib/classes/grading-cost";

import { ScoringCalculator } from "./scoring-calculator";

type Field = "scoring_method" | "quality_method";

const ROWS: { field: Field; label: string; testId: string }[] = [
  { field: "scoring_method", label: "채점 방식", testId: "scoring-method" },
  { field: "quality_method", label: "완성도 검사 방식", testId: "quality-method" },
];

const METHOD_LABEL: Record<GradingMethod, string> = { single: "한 번 호출", agent: "에이전트" };

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
  ].join(":");
}
