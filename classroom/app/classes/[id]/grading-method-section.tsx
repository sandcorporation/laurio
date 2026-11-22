"use client";

import { useState } from "react";

import { ErrorNote, FieldLabel, INPUT_CLASS } from "@/app/components/ui";
import { updateClass, type ClassRow, type GradingMethod, type OversizePolicy } from "@/lib/classes/api";
import { AGENT_MODEL_TOOLTIP, UNAVAILABLE_TOOLTIP, vendorLabel } from "@/lib/classes/grading-cost";

import { ScoringCalculator } from "./scoring-calculator";

type Field = "scoring_method" | "quality_method";
type Saving = Field | "oversize";

const ROWS: { field: Field; label: string; testId: string }[] = [
  { field: "scoring_method", label: "채점 방식", testId: "scoring-method" },
  { field: "quality_method", label: "완성도 검사 방식", testId: "quality-method" },
];

export const METHOD_LABEL: Record<GradingMethod, string> = { single: "한 번 호출", agent: "에이전트" };

export const OVERSIZE_LABEL: Record<OversizePolicy, string> = {
  reject: "반려",
  agent: "에이전트로 채점",
  partial: "들어가는 파일만",
};
const OVERSIZE_ORDER: OversizePolicy[] = ["reject", "agent", "partial"];

function radioClass(checked: boolean): string {
  return `px-3 py-1.5 text-[13px] disabled:cursor-not-allowed ${
    checked ? "bg-ink text-surface" : "bg-surface text-ink disabled:text-ink/35"
  }`;
}

export function GradingMethodSection({ classId, classroom, onSaved }: { classId: number; classroom: ClassRow; onSaved: () => void }) {
  const [saving, setSaving] = useState<Saving | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 「에이전트로 채점」을 눌렀는데 아직 모델이 없으면 모델을 고를 때까지 저장하지 않는다(서버가 빈 모델을 거절한다).
  const [pickingAgent, setPickingAgent] = useState(false);
  const vendor = vendorLabel(classroom.scoring_connection_kind);
  const agentOption = classroom.grading_method_options.find((o) => o.value === "agent");
  const agentBlockedBy = agentOption?.unavailable_reason ? UNAVAILABLE_TOOLTIP[agentOption.unavailable_reason] : undefined;
  const defaultModelTakesAgent = classroom.agent_models.includes(classroom.default_model);

  async function save(target: Saving, patch: Parameters<typeof updateClass>[1]) {
    setSaving(target);
    setError(null);
    const result = await updateClass(classId, patch);
    if (result.ok) onSaved();
    else setError(result.detail);
    setSaving(null);
    return result.ok;
  }

  async function choose(field: Field, value: GradingMethod) {
    if (classroom[field] === value) return;
    await save(field, { [field]: value });
  }

  async function chooseOversize(value: OversizePolicy) {
    if (value === "agent" && !classroom.oversize_agent_model) {
      setPickingAgent(true);
      return;
    }
    setPickingAgent(false);
    if (classroom.oversize_policy === value) return;
    await save("oversize", { oversize_policy: value });
  }

  async function chooseAgentModel(model: string) {
    if (!model) return;
    if (await save("oversize", { oversize_policy: "agent", oversize_agent_model: model })) setPickingAgent(false);
  }

  const shownOversize: OversizePolicy = pickingAgent ? "agent" : classroom.oversize_policy;

  return (
    <div className="flex flex-col gap-4 p-4">
      {ROWS.map(({ field, label, testId }) => (
        <div key={field} className="flex flex-col gap-1.5" data-testid={testId}>
          <FieldLabel>{label}</FieldLabel>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <div role="radiogroup" aria-label={label} className="inline-flex border border-rule">
              {classroom.grading_method_options.map((option) => {
                const checked = classroom[field] === option.value;
                // 에이전트는 기본 모델이 받는 모델일 때만 고른다(#1311) — 이미 고른 것은 그대로 보인다.
                const modelBlocked = option.value === "agent" && !checked && !defaultModelTakesAgent;
                const reason = option.unavailable_reason
                  ? UNAVAILABLE_TOOLTIP[option.unavailable_reason]
                  : modelBlocked
                    ? AGENT_MODEL_TOOLTIP
                    : undefined;
                const selectable = option.selectable && !modelBlocked;
                return (
                  <button
                    key={option.value}
                    type="button"
                    role="radio"
                    aria-checked={checked}
                    data-testid={`${testId}-${option.value}`}
                    disabled={!selectable || saving !== null}
                    title={selectable ? undefined : reason}
                    onClick={() => void choose(field, option.value)}
                    className={radioClass(checked)}
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
      {classroom.scoring_method === "agent" ? null : (
        <div className="flex flex-col gap-1.5" data-testid="oversize-policy">
          <FieldLabel>한 번 호출로 못 담는 제출물</FieldLabel>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <div role="radiogroup" aria-label="한 번 호출로 못 담는 제출물" className="inline-flex flex-wrap border border-rule">
              {OVERSIZE_ORDER.map((value) => {
                const blocked = value === "agent" ? agentBlockedBy : undefined;
                return (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={shownOversize === value}
                    data-testid={`oversize-policy-${value}`}
                    disabled={Boolean(blocked) || saving !== null}
                    title={blocked}
                    onClick={() => void chooseOversize(value)}
                    className={radioClass(shownOversize === value)}
                  >
                    {OVERSIZE_LABEL[value]}
                  </button>
                );
              })}
            </div>
            {shownOversize === "agent" ? (
              <select
                aria-label="에이전트로 채점할 모델"
                data-testid="oversize-agent-model"
                className={`${INPUT_CLASS} w-auto`}
                value={classroom.agent_models.includes(classroom.oversize_agent_model) ? classroom.oversize_agent_model : ""}
                disabled={saving !== null}
                onChange={(event) => void chooseAgentModel(event.target.value)}
              >
                <option value="" disabled>
                  모델 고르기
                </option>
                {classroom.agent_models.map((model) => (
                  <option key={model} value={model}>
                    {model}
                  </option>
                ))}
              </select>
            ) : null}
          </div>
        </div>
      )}
      {error ? (
        <ErrorNote>
          <span data-testid="grading-method-error">{error}</span>
        </ErrorNote>
      ) : null}
    </div>
  );
}

/** 예상 비용 — 실제 설정이 아니라 바꿔 보는 계산기. */
export function CostEstimateSection({ classId, classroom }: { classId: number; classroom: ClassRow }) {
  return (
    <div className="p-4">
      <ScoringCalculator key={calculatorKey(classroom)} classId={classId} />
    </div>
  );
}

// 키 저장·연결·방식·기본 모델·못 담는 제출물 설정이 바뀌면 계산기를 처음 값(지금 이 클래스의 조합)부터 다시 받는다.
function calculatorKey(classroom: ClassRow): string {
  return [
    classroom.scoring_connection_kind,
    classroom.openai_key ? "openai" : "",
    classroom.anthropic_key ? "anthropic" : "",
    classroom.scoring_method,
    classroom.default_model,
    classroom.oversize_policy,
    classroom.oversize_agent_model,
  ].join(":");
}
