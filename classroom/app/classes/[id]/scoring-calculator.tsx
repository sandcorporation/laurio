"use client";

// 채점 비용 예상표(#1270·#1304) — 프로바이더 × 방식 × 모델의 제출 한 건 예상이 한 표에 서고, 가정(소스 크기·항목 수·학생 수…)은
// 라벨과 값으로 보이며 바꿔 볼 수 있다. 바꾼 값은 저장하지 않는다. 처음 표시된 칸은 지금 이 클래스의 조합이다.
import { useState, type ReactNode } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { Badge, ErrorNote, FieldLabel, INPUT_CLASS } from "@/app/components/ui";
import { bffClient } from "@/lib/bff/client";
import {
  agentLimitsLine,
  agentNote,
  calculatorPath,
  changeChoice,
  escalationCost,
  formatUsdPerMillion,
  fromLabel,
  parseAssumption,
  providerLabel,
  semesterLine,
  singleNote,
  singleTimeLabel,
  sourceLabel,
  twoStepLine,
  type AssumptionField,
  type CalculatorChoice,
  type CalculatorMethod,
  type CalculatorRow,
  type ScoringCalculator as Calculation,
} from "@/lib/scoring/calculator";
import { formatKrw } from "@/lib/scoring/cost";

const SELECTED_CELL = "bg-paper font-medium text-ink";

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
  const change = (field: keyof CalculatorChoice, value: string | number | undefined) =>
    setChoice((current) => changeChoice({ ...fromSelection(calc), ...current }, field, value));
  const pick = (row: CalculatorRow, method: CalculatorMethod) =>
    setChoice((current) => ({ ...current, vendor: row.vendor, model: row.model_id, method }));

  return (
    <div data-testid="scoring-calculator" className="flex flex-col gap-4">
      <Assumptions calc={calc} change={change} />
      <ModelTable calc={calc} pick={pick} />
      <Semester calc={calc} />
      <CapacityLines calc={calc} />
      <EscalationLine calc={calc} />
    </div>
  );
}

function Assumptions({
  calc,
  change,
}: {
  calc: Calculation;
  change: (field: keyof CalculatorChoice, value: string | number | undefined) => void;
}) {
  const { assumptions: a, defaults: d, selection, problems } = calc;
  const problem = problems.find((p) => p.id === selection.problem_id);
  const sources = problem?.sources ?? [
    { key: "median", chars: d.source_chars_median, measured: false },
    { key: "p90", chars: d.source_chars_p90, measured: false },
  ];
  return (
    <div data-testid="calculator-assumptions" className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
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
      <Field label="제출 크기" tag={fromLabel(a.source_from)}>
        <select
          data-testid="calculator-source"
          aria-label="제출 크기"
          className={INPUT_CLASS}
          value={selection.source === "custom" ? "custom" : selection.source}
          onChange={(e) => (e.target.value === "custom" ? change("sourceChars", a.source_chars) : change("source", e.target.value))}
        >
          {sources.map((s) => (
            <option key={s.key} value={s.key}>
              {sourceLabel(s)}
            </option>
          ))}
          {selection.source === "custom" ? <option value="custom">입력 · {a.source_chars.toLocaleString("ko-KR")} 자</option> : null}
        </select>
        <NumberInput
          testId="calculator-source-chars"
          label="제출 크기(자)"
          value={a.source_chars}
          onCommit={(value) => change("sourceChars", value)}
        />
      </Field>
      <Field label="항목 수" tag={fromLabel(a.requirements_from)}>
        <NumberInput
          testId="calculator-requirements"
          label="항목 수"
          value={a.requirements}
          placeholder={String(d.requirements)}
          onCommit={(value) => change("requirements", value)}
        />
      </Field>
      <Field label="학생 수" tag="가정">
        <NumberInput
          testId="calculator-students"
          label="학생 수"
          value={a.students}
          placeholder={String(d.students)}
          onCommit={(value) => change("students", value)}
        />
      </Field>
      <Field label="과제 수" tag="가정">
        <NumberInput
          testId="calculator-assignments"
          label="과제 수"
          value={a.assignments}
          placeholder={String(d.assignments)}
          onCommit={(value) => change("assignments", value)}
        />
      </Field>
      <Field label="재채점 비율" tag="가정">
        <NumberInput
          testId="calculator-regrade-rate"
          label="재채점 비율"
          value={a.regrade_rate}
          placeholder={String(d.regrade_rate)}
          onCommit={(value) => change("regradeRate", value)}
        />
      </Field>
      <Field label="의심 비율" tag="가정">
        <NumberInput
          testId="calculator-suspect-rate"
          label="의심 비율"
          value={a.suspect_rate}
          placeholder={String(d.suspect_rate)}
          onCommit={(value) => change("suspectRate", value)}
        />
      </Field>
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

function ModelTable({ calc, pick }: { calc: Calculation; pick: (row: CalculatorRow, method: CalculatorMethod) => void }) {
  const { selection } = calc;
  const isSelected = (row: CalculatorRow, method: CalculatorMethod) =>
    row.model_id === selection.model_id && method === selection.method;
  return (
    <table data-testid="calculator-table" className="w-full table-fixed border-collapse text-[13px]">
      <thead>
        <tr className="border-b border-rule text-left text-[12px] text-ink/60">
          <th className="w-[34%] py-1.5 pr-2 font-normal">모델</th>
          <th className="px-2 py-1.5 font-normal">
            한 번 호출
            {calc.staged.enabled ? <span className="ml-1 text-ink/45">· 근거 인용</span> : null}
          </th>
          <th className="px-2 py-1.5 font-normal">에이전트</th>
        </tr>
      </thead>
      {calc.providers.map((provider) => (
        <tbody key={provider.vendor} data-testid={`calculator-provider-${provider.vendor}`}>
          <tr className="border-b border-rule/60 bg-paper/50">
            <th colSpan={3} scope="colgroup" className="py-1.5 pr-2 text-left text-[12px] font-medium text-ink/70">
              {providerLabel(provider.vendor)}
              {provider.has_key ? null : (
                <span data-testid={`calculator-no-key-${provider.vendor}`} className="ml-2">
                  <Badge tone="warning">키 없음</Badge>
                </span>
              )}
            </th>
          </tr>
          {provider.models.map((model) => {
            const row = calc.rows.find((r) => r.model_id === model.id);
            if (!row) return null;
            return (
              <tr key={model.id} data-testid={`calculator-row-${model.id}`} className="border-b border-rule/60 align-top">
                <th scope="row" className="py-1.5 pr-2 text-left font-normal">
                  <span className="block break-all font-mono text-[12px] text-ink">{model.id}</span>
                  <span className="block text-[11px] text-ink/50">
                    {formatUsdPerMillion(model.input_usd_per_million, model.output_usd_per_million)}
                  </span>
                </th>
                <td className="px-2 py-1.5">
                  <CellButton
                    testId={`calculator-cell-${model.id}-single`}
                    selected={isSelected(row, "single")}
                    onClick={() => pick(row, "single")}
                  >
                    <span data-testid={`calculator-cost-${model.id}-single`} className="block text-ink">
                      {row.single.route === "hold" ? "0원" : formatKrw(row.single.krw, row.single.open_ended)}
                    </span>
                    <span
                      data-testid={`calculator-note-${model.id}-single`}
                      className={`block text-[11px] ${row.single.route === "hold" ? "text-warning" : "text-ink/55"}`}
                    >
                      {singleNote(row.single, calc.staged)}
                    </span>
                    <span className="block text-[11px] text-ink/45">{singleTimeLabel(row.single)}</span>
                  </CellButton>
                </td>
                <td className="px-2 py-1.5">
                  {row.agent.available && row.agent.krw != null ? (
                    <CellButton
                      testId={`calculator-cell-${model.id}-agent`}
                      selected={isSelected(row, "agent")}
                      onClick={() => pick(row, "agent")}
                    >
                      <span data-testid={`calculator-cost-${model.id}-agent`} className="block text-ink">
                        {formatKrw(row.agent.krw)}
                      </span>
                      <span data-testid={`calculator-note-${model.id}-agent`} className="block text-[11px] text-ink/55">
                        {agentNote(row.agent)}
                      </span>
                    </CellButton>
                  ) : (
                    <span data-testid={`calculator-agent-unsupported-${model.id}`} className="text-ink/45">
                      지원 안 함
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      ))}
    </table>
  );
}

function CellButton({
  testId,
  selected,
  onClick,
  children,
}: {
  testId: string;
  selected: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      aria-pressed={selected}
      onClick={onClick}
      className={`w-full min-w-0 px-1.5 py-1 text-left break-words ${selected ? SELECTED_CELL : "text-ink/70"} ${
        selected ? "border border-ink" : "border border-transparent hover:border-rule"
      }`}
    >
      {children}
    </button>
  );
}

function Semester({ calc }: { calc: Calculation }) {
  const line = semesterLine(calc);
  return (
    <div data-testid="calculator-semester" className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[13px]">
      <span className="text-[12px] text-ink/60">클래스 한 학기</span>
      <span data-testid="calculator-semester-total" className="text-[18px] text-ink">
        {line.total}
      </span>
      <span data-testid="calculator-semester-formula" className="text-ink/60">
        {line.formula}
      </span>
      <span data-testid="calculator-semester-model" className="font-mono text-[12px] text-ink/50">
        {calc.selection.model_id} · {calc.selection.method === "agent" ? "에이전트" : "한 번 호출"}
      </span>
    </div>
  );
}

function CapacityLines({ calc }: { calc: Calculation }) {
  return (
    <dl data-testid="calculator-capacity" className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[13px]">
      <dt className="text-[12px] text-ink/60">한 번 호출</dt>
      <dd data-testid="calculator-capacity-single" className="text-ink/80">
        모델마다 감당 글자 수까지 — 넘으면 담지 못함, 보류(채점 안 함)
      </dd>
      {calc.staged.enabled ? (
        <>
          <dt className="text-[12px] text-ink/60">새 채점기</dt>
          <dd data-testid="calculator-capacity-staged" className="text-ink/80">
            {twoStepLine(calc.staged)} — 1차 목록이 모델 예산을 넘으면 보류
          </dd>
        </>
      ) : null}
      <dt className="text-[12px] text-ink/60">에이전트</dt>
      <dd data-testid="calculator-capacity-agent" className="text-ink/80">
        {agentLimitsLine(calc.agent_limits)}
      </dd>
    </dl>
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
            의심 비율 {line.rate} <span className="text-[11px] text-ink/45">가정</span>
          </span>
          <span data-testid="calculator-escalation-per-submission" className="text-ink/60">
            {line.perSubmission}
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
    students: a.students,
    assignments: a.assignments,
    regradeRate: a.regrade_rate,
    suspectRate: a.suspect_rate,
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
