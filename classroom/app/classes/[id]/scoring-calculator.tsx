"use client";

// 채점 비용 계산기(#1270) — 프로바이더 × 방식 × 모델 × 체크리스트 × 소스 크기를 고르면 제출 한 건 예상과 두 방식의
// 차이가 나란히 선다. 처음 값은 지금 이 클래스의 조합이다. 고른 값은 저장하지 않는다.
import { useState, type ReactNode } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { Badge, ErrorNote, FieldLabel, INPUT_CLASS } from "@/app/components/ui";
import { bffClient } from "@/lib/bff/client";
import {
  agentConnectionsLabel,
  agentOnlyLabel,
  calculatorPath,
  changeChoice,
  escalationCost,
  headline,
  NO_MEASUREMENT,
  providerLabel,
  sourceLabel,
  spreadKrw,
  spreadSeconds,
  formatUsdPerMillion,
  type CalculatorChoice,
  type CalculatorMethod,
  type ScoringCalculator as Calculation,
} from "@/lib/scoring/calculator";
import { formatKrw } from "@/lib/scoring/cost";

const METHODS: { value: CalculatorMethod; label: string }[] = [
  { value: "single", label: "한 번 호출" },
  { value: "agent", label: "에이전트" },
];

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
  const { selection } = calc;
  const change = (field: keyof CalculatorChoice, value: string | number) =>
    setChoice((current) => changeChoice({ ...fromSelection(calc), ...current }, field, value));
  const provider = calc.providers.find((p) => p.vendor === selection.vendor);
  const model = provider?.models.find((m) => m.id === selection.model_id);
  const problem = calc.problems.find((p) => p.id === selection.problem_id);
  const sources = problem?.sources ?? [];
  const agentOk = calc.agent.available;
  const methodCell = (method: CalculatorMethod) =>
    method === selection.method ? "bg-paper font-medium text-ink" : "text-ink/70";

  return (
    <div data-testid="scoring-calculator" className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
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
          {provider && !provider.has_key ? (
            <span data-testid="calculator-no-key">
              <Badge tone="warning">키 없음</Badge>
            </span>
          ) : null}
        </Field>
        <Field label="채점 방식">
          <div role="radiogroup" aria-label="계산기 채점 방식" className="inline-flex w-fit border border-rule">
            {METHODS.map(({ value, label }) => {
              const disabled = value === "agent" && !agentOk;
              return (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={selection.method === value}
                  data-testid={`calculator-method-${value}`}
                  disabled={disabled}
                  title={disabled ? agentOnlyLabel(calc.agent_vendors) : undefined}
                  onClick={() => change("method", value)}
                  className={`px-3 py-1.5 text-[13px] disabled:cursor-not-allowed ${
                    selection.method === value ? "bg-ink text-surface" : "bg-surface text-ink disabled:text-ink/35"
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>
          {!agentOk ? (
            <span data-testid="calculator-agent-unavailable" className="text-[12px] text-ink/50">
              에이전트 {agentOnlyLabel(calc.agent_vendors)}
            </span>
          ) : null}
        </Field>
        <Field label="모델">
          <select
            data-testid="calculator-model"
            aria-label="모델"
            className={INPUT_CLASS}
            value={selection.model_id}
            onChange={(e) => change("model", e.target.value)}
          >
            {(provider?.models ?? []).map((m) => (
              <option key={m.id} value={m.id}>
                {m.id}
              </option>
            ))}
          </select>
          {model ? (
            <span data-testid="calculator-unit-price" className="text-[12px] text-ink/50">
              {formatUsdPerMillion(model.input_usd_per_million, model.output_usd_per_million)}
            </span>
          ) : null}
        </Field>
        <Field label="체크리스트">
          {calc.problems.length > 0 ? (
            <select
              data-testid="calculator-problem"
              aria-label="체크리스트"
              className={INPUT_CLASS}
              value={selection.problem_id ?? ""}
              onChange={(e) => change("problemId", e.target.value)}
            >
              {calc.problems.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title} · 요구사항 {p.requirement_count}개
                </option>
              ))}
            </select>
          ) : (
            <span data-testid="calculator-no-problem" className="text-[13px] text-ink/45">
              문제 없음
            </span>
          )}
        </Field>
        <Field label="소스 크기">
          <select
            data-testid="calculator-source"
            aria-label="소스 크기"
            className={INPUT_CLASS}
            value={selection.source}
            onChange={(e) => change("source", e.target.value)}
          >
            {(sources.length > 0 ? sources : [{ key: selection.source, chars: selection.source_chars, measured: false }]).map(
              (s) => (
                <option key={s.key} value={s.key}>
                  {sourceLabel(s)}
                </option>
              ),
            )}
          </select>
        </Field>
        <Field label="제출 한 건">
          <span data-testid="calculator-headline" className="text-[18px] text-ink">
            {headline(calc)}
          </span>
        </Field>
      </div>

      <table data-testid="calculator-compare" className="w-full table-fixed border-collapse text-[13px]">
        <thead>
          <tr className="border-b border-rule text-left text-[12px] text-ink/60">
            <th className="w-[22%] py-1.5 pr-2 font-normal" />
            {METHODS.map(({ value, label }) => (
              <th key={value} className={`px-2 py-1.5 font-normal ${methodCell(value)}`}>
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <CompareRow
            label="건당"
            testId="compare-cost"
            single={formatKrw(calc.single.krw, calc.single.open_ended)}
            agent={agentOk ? spreadKrw(calc.agent.krw) : NO_MEASUREMENT}
            cell={methodCell}
          />
          <CompareRow
            label="시간"
            testId="compare-time"
            single={spreadSeconds(calc.single.seconds)}
            agent={agentOk ? spreadSeconds(calc.agent.seconds) : NO_MEASUREMENT}
            cell={methodCell}
          />
          <CompareRow
            label="담는 크기"
            testId="compare-size"
            single={calc.single.fits ? "모델 한도까지" : "크기 초과"}
            agent="파일을 골라 읽음"
            cell={methodCell}
          />
          <CompareRow
            label="되는 연결"
            testId="compare-connections"
            single="전부"
            agent={agentConnectionsLabel(calc.agent_vendors)}
            cell={methodCell}
          />
        </tbody>
      </table>
      <EscalationLine calc={calc} />
    </div>
  );
}

function EscalationLine({ calc }: { calc: Calculation }) {
  const line = escalationCost(calc.escalation);
  return (
    <div data-testid="calculator-escalation" className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[13px]">
      <span className="text-[12px] text-ink/60">의심 재판정</span>
      {line ? (
        <>
          <span data-testid="calculator-escalation-model" className="font-mono text-ink/70">
            {line.model}
          </span>
          <span data-testid="calculator-escalation-cost" className="text-ink">
            {line.perSuspect}
          </span>
          <span data-testid="calculator-escalation-rate" className="text-ink/60">
            의심 비율 {line.rate}
          </span>
        </>
      ) : (
        <span data-testid="calculator-escalation-off" className="text-ink/60">
          끔
        </span>
      )}
    </div>
  );
}

function fromSelection(calc: Calculation): CalculatorChoice {
  const s = calc.selection;
  return {
    vendor: s.vendor,
    method: s.method === "agent" ? "agent" : "single",
    model: s.model_id,
    problemId: s.problem_id ?? undefined,
    source: s.source,
  };
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <FieldLabel>{label}</FieldLabel>
      {children}
    </div>
  );
}

function CompareRow({
  label,
  testId,
  single,
  agent,
  cell,
}: {
  label: string;
  testId: string;
  single: string;
  agent: string;
  cell: (method: CalculatorMethod) => string;
}) {
  return (
    <tr data-testid={testId} className="border-b border-rule/60 align-top">
      <th scope="row" className="py-1.5 pr-2 text-left text-[12px] font-normal text-ink/60">
        {label}
      </th>
      <td data-testid={`${testId}-single`} className={`px-2 py-1.5 break-words ${cell("single")}`}>
        {single}
      </td>
      <td data-testid={`${testId}-agent`} className={`px-2 py-1.5 break-words ${cell("agent")}`}>
        {agent}
      </td>
    </tr>
  );
}
