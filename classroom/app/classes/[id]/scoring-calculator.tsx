"use client";

// 채점 비용 계산기(#1270·#1304·#1308) — 프로바이더·방식·모델을 고르고 소스 파일 수·항목 수를 넣으면 제출 한 건 금액이 나온다.
// 처음 값은 지금 이 클래스의 조합이다. 바꾼 값은 저장하지 않는다.
import { useState, type ReactNode } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { ErrorNote, FieldLabel, INPUT_CLASS } from "@/app/components/ui";
import { bffClient } from "@/lib/bff/client";
import {
  agentModelIds,
  calculatorPath,
  cheapestAgentModel,
  capacityText,
  changeChoice,
  charsLabel,
  listedModels,
  parseAssumption,
  providerLabel,
  submissionAmount,
  submissionBasis,
  type CalculatorChoice,
  type ScoringCalculator as Calculation,
} from "@/lib/scoring/calculator";

import { METHOD_LABEL } from "./grading-method-section";

export function ScoringCalculator({ classId }: { classId: number }) {
  const [choice, setChoice] = useState<CalculatorChoice>({});
  const { state } = useBackendQuery<Calculation>(bffClient, calculatorPath(classId, choice));

  if (state.status === "loading") {
    return (
      <p data-testid="scoring-calculator-loading" className="text-[13px] text-ink/45">
        불러오는 중...
      </p>
    );
  }
  if (state.status === "error") {
    return (
      <ErrorNote>
        <span data-testid="scoring-calculator-error">예상 비용을 불러오지 못했습니다.</span>
      </ErrorNote>
    );
  }
  const calc = state.data;
  const { selection, assumptions: a, problems } = calc;
  // 에이전트는 모델마다 다르다(#1311) — OpenAI 는 gpt-5-mini 이상만.
  const agentIds = agentModelIds(calc, selection.vendor);
  const agentOk = agentIds.has(selection.model_id);
  // 호환 서버처럼 에이전트가 되는 모델이 하나도 없으면 「에이전트」를 끈다.
  const agentPossible = agentIds.size > 0;
  const change = (field: keyof CalculatorChoice, value: string | number | undefined) =>
    setChoice((current) => {
      const next = changeChoice({ ...fromSelection(calc), ...current }, field, value);
      // 에이전트가 안 되는 모델에서 「에이전트」를 고르면, 되는 모델 중 입력 단가가 가장 싼 것으로 바꾼다.
      if (field === "method" && value === "agent" && !agentOk) {
        const model = cheapestAgentModel(calc, selection.vendor);
        if (model) return { ...next, model };
      }
      return next;
    });
  const models = listedModels(calc);

  return (
    <div data-testid="scoring-calculator" className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field label="프로바이더">
          <select
            data-testid="calculator-vendor"
            aria-label="프로바이더"
            className={INPUT_CLASS}
            value={selection.vendor}
            onChange={(e) => change("vendor", e.target.value)}
          >
            {calc.providers.map((p) => (
              <option key={p.vendor} value={p.vendor}>
                {providerLabel(p.vendor)}
                {p.has_key ? "" : " — 키 없음"}
              </option>
            ))}
          </select>
        </Field>
        <Field label="방식">
          <select
            data-testid="calculator-method"
            aria-label="방식"
            className={INPUT_CLASS}
            value={selection.method}
            onChange={(e) => change("method", e.target.value)}
          >
            <option value="single">{METHOD_LABEL.single}</option>
            <option value="agent" disabled={!agentPossible}>
              {METHOD_LABEL.agent}
            </option>
          </select>
        </Field>
        <Field label="모델">
          <select
            data-testid="calculator-model"
            aria-label="모델"
            className={INPUT_CLASS}
            value={selection.model_id}
            onChange={(e) => change("model", e.target.value)}
          >
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.id}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {problems.length > 0 ? (
          <Field label="체크리스트">
            <select
              data-testid="calculator-problem"
              aria-label="체크리스트"
              className={INPUT_CLASS}
              value={selection.problem_id ?? ""}
              onChange={(e) => change("problemId", e.target.value)}
            >
              {problems.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title} · 항목 {p.requirement_count}개
                </option>
              ))}
            </select>
          </Field>
        ) : null}
        <Field label="소스 파일">
          <div className="flex items-center gap-2">
            <div className="w-24">
              <NumberInput
                testId="calculator-source-files"
                label="소스 파일 수"
                value={a.source_files}
                onCommit={(value) => change("sourceChars", value === undefined ? undefined : value * a.source_chars_per_file)}
              />
            </div>
            <span data-testid="calculator-source-chars" className="text-[13px] text-ink/70">
              개 ({charsLabel(a.source_chars)})
            </span>
          </div>
        </Field>
        <Field label="항목">
          <div className="flex items-center gap-2">
            <div className="w-24">
              <NumberInput
                testId="calculator-requirements"
                label="항목 수"
                value={a.requirements}
                onCommit={(value) => change("requirements", value)}
              />
            </div>
            <span className="text-[13px] text-ink/70">개</span>
          </div>
        </Field>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[14px]">
        <dt className="text-[12px] text-ink/60">제출 한 건</dt>
        <dd data-testid="calculator-amount" className="text-ink">
          {submissionAmount(calc)}
        </dd>
        <dd data-testid="calculator-amount-basis" className="col-start-2 -mt-0.5 text-[11.5px] text-ink/45">
          {submissionBasis(calc)}
        </dd>
        <dt className="text-[12px] text-ink/60">담는 크기</dt>
        <dd data-testid="calculator-capacity" className="text-ink/80">
          {capacityText(calc)}
        </dd>
      </dl>
    </div>
  );
}

/** 값을 쓰는 동안은 보내지 않고, 칸을 벗어나거나 Enter 를 누르면 그 값으로 다시 셈한다. */
function NumberInput({
  testId,
  label,
  value,
  placeholder,
  onCommit,
}: {
  testId: string;
  label: string;
  value: number;
  placeholder?: string;
  onCommit: (value: number | undefined) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft === null) return;
    const parsed = parseAssumption(draft);
    setDraft(null);
    if (parsed !== value) onCommit(parsed);
  };
  return (
    <input
      data-testid={testId}
      aria-label={label}
      inputMode="decimal"
      className={INPUT_CLASS}
      placeholder={placeholder}
      value={draft ?? String(value)}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
      }}
    />
  );
}

function fromSelection(calc: Calculation): CalculatorChoice {
  const s = calc.selection;
  const a = calc.assumptions;
  return {
    vendor: s.vendor,
    method: s.method === "agent" ? "agent" : "single",
    model: s.model_id,
    problemId: s.problem_id ?? undefined,
    // 고르기만 한 소스는 키로, 입력한 글자 수는 값으로 — 다른 칸을 바꿀 때 그대로 따라간다.
    source: s.source === "custom" ? undefined : s.source,
    sourceChars: s.source === "custom" ? s.source_chars : undefined,
    requirements: a.requirements_from === "custom" ? a.requirements : undefined,
  };
}

function Field({ label, tag, children }: { label: string; tag?: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <FieldLabel>
        {label}
        {tag ? (
          <span data-testid="calculator-field-tag" className="ml-1.5 text-[11px] font-normal text-ink/45">
            {tag}
          </span>
        ) : null}
      </FieldLabel>
      {children}
    </div>
  );
}
