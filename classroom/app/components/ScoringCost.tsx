"use client";

// 예상 채점 비용 (#591) — 강사가 모델·추론 강도를 고르는 바로 그 자리에서 시도 하나와 문제
// 하나가 얼마인지 보인다. 「클래스 설정 › 채점」은 모델별 표를, 「문제 설정 › 채점 모델」은
// 이 문제가 실제로 쓸 설정 한 줄을 보인다. 값은 서버가 셈한 것(`useScoringCost`)이고, 이
// 파일은 고른 모델·강도의 줄을 찾아 적기만 한다(`lib/scoring/cost.ts`).
import { Badge, buttonClass } from "@/app/components/ui";
import {
  attemptsWithinBudget,
  costBasisText,
  costRowLabel,
  findCostRow,
  formatAttemptsPerParticipant,
  formatKrw,
  formatManCount,
  formatRatio,
  type ScoringCostEstimate,
  type ScoringCostRow,
} from "@/lib/scoring/cost";
import type { ScoringCostState } from "@/lib/scoring/use-scoring-cost";

const BILLING_NOTE = "실제 청구액은 OpenAI 사용량 화면이 기준입니다.";
const UNPRICED = "비용 미확인";

function CurrentBadge() {
  return (
    <span className="ml-2 inline-flex shrink-0">
      <Badge>지금 설정</Badge>
    </span>
  );
}

function ratioText(row: ScoringCostRow): string {
  return row.ratio_to_baseline === null ? "—" : formatRatio(row.ratio_to_baseline, row.open_ended);
}

// 표의 줄: 단가를 아는 줄 + 지금 고른 설정(단가를 몰라도 한 줄, 「비용 미확인」).
function tableRows(
  estimate: ScoringCostEstimate,
  modelId: string,
  reasoningEffort: string,
  isReasoning: boolean,
): { rows: ScoringCostRow[]; current: ScoringCostRow } {
  const priced = estimate.rows.filter((row) => row.priced);
  const found = findCostRow(estimate, modelId, reasoningEffort);
  const current: ScoringCostRow = found ?? {
    model_id: modelId,
    reasoning_effort: isReasoning ? reasoningEffort : null,
    priced: false,
    open_ended: false,
    per_attempt: null,
    per_problem_krw: null,
    ratio_to_baseline: null,
    by_source_size: [],
  };
  return { rows: current.priced ? priced : [...priced, current], current };
}

const CELL = "border-b border-rule/60 px-3.5 py-2.5";
const NUM_CELL = `${CELL} whitespace-nowrap text-right font-mono text-[12.5px]`;
const HEAD_CELL = "border-b border-rule px-3.5 py-2 text-[11.5px] text-ink/45";

export function ClassScoringCostTable({
  state,
  modelId,
  reasoningEffort,
  isReasoning,
}: {
  state: ScoringCostState;
  modelId: string;
  reasoningEffort: string;
  isReasoning: boolean;
}) {
  if (state.status !== "ready") return null;
  const { estimate } = state;
  const { rows, current } = tableRows(estimate, modelId, reasoningEffort, isReasoning);
  const bySize = estimate.basis === "source_sizes";
  const isCurrent = (row: ScoringCostRow) =>
    row.model_id === current.model_id && row.reasoning_effort === current.reasoning_effort;

  return (
    <div className="flex flex-col gap-3">
      <div data-testid="class-scoring-cost" className="border border-rule">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-rule px-3.5 py-3">
          <h3 className="text-[13.5px] font-semibold">모델별 예상 채점 비용</h3>
          <span data-testid="class-scoring-cost-basis" className="text-[11.5px] text-ink/45">
            {costBasisText(estimate, "class")}
          </span>
        </div>
        {/* 좁은 화면은 줄마다 세로로 — 네 칸 표가 390px 에 들어가지 않는다. */}
        <ul className="sm:hidden">
          {rows.map((row) => {
            const selected = isCurrent(row);
            const values: [string, string][] = !row.priced
              ? []
              : bySize
                ? row.by_source_size.map((cost, index) => [
                    `소스 약 ${formatManCount(estimate.source_size_bands[index] ?? 0)} 자`,
                    formatKrw(cost.krw, row.open_ended),
                  ])
                : [
                    ["시도 1건", row.per_attempt ? formatKrw(row.per_attempt.krw, row.open_ended) : "—"],
                    [
                      `문제 하나 · ${estimate.participant_count}명`,
                      row.per_problem_krw && estimate.participant_count > 0
                        ? formatKrw(row.per_problem_krw, row.open_ended)
                        : "—",
                    ],
                    ["배율", ratioText(row)],
                  ];
            return (
              <li
                key={`${row.model_id}:${row.reasoning_effort ?? ""}`}
                className={`flex flex-col gap-1.5 border-b border-rule/60 px-3.5 py-2.5 text-[13px] ${selected ? "bg-paper" : ""}`}
              >
                <span className="inline-flex flex-wrap items-center">
                  <span className={selected ? "font-semibold" : ""}>{costRowLabel(row)}</span>
                  {selected ? <CurrentBadge /> : null}
                </span>
                {row.priced ? (
                  <dl className="grid grid-cols-3 gap-2">
                    {values.map(([label, value]) => (
                      <div key={label} className="flex min-w-0 flex-col">
                        <dt className="text-[11px] text-ink/45">{label}</dt>
                        <dd className="whitespace-nowrap font-mono text-[12.5px]">{value}</dd>
                      </div>
                    ))}
                  </dl>
                ) : (
                  <span className="text-[12.5px] text-ink/45">{UNPRICED}</span>
                )}
              </li>
            );
          })}
        </ul>
        <div className="hidden sm:block">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr>
                <th className={`${HEAD_CELL} text-left font-normal`}>{bySize ? "모델 · 시도 1건" : "모델"}</th>
                {bySize ? (
                  estimate.source_size_bands.map((chars, index) => (
                    <th key={chars} className={`${HEAD_CELL} text-right font-normal`}>
                      {["작은 과제", "보통", "큰 프로젝트"][index] ?? ""}
                      <br />
                      소스 약 {formatManCount(chars)} 자
                    </th>
                  ))
                ) : (
                  <>
                    <th className={`${HEAD_CELL} text-right font-normal`}>시도 1건</th>
                    <th className={`${HEAD_CELL} text-right font-normal`}>
                      문제 하나 · {estimate.participant_count}명
                    </th>
                    <th className={`${HEAD_CELL} text-right font-normal`}>배율</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const selected = isCurrent(row);
                const tone = selected ? "bg-paper font-medium" : "";
                return (
                  <tr
                    key={`${row.model_id}:${row.reasoning_effort ?? ""}`}
                    data-testid={`class-scoring-cost-row-${row.model_id}${row.reasoning_effort ? `-${row.reasoning_effort}` : ""}`}
                    className={tone}
                  >
                    <td className={CELL}>
                      <span className="inline-flex flex-wrap items-center">
                        <span className={selected ? "font-semibold" : ""}>{costRowLabel(row)}</span>
                        {selected ? <CurrentBadge /> : null}
                      </span>
                    </td>
                    {!row.priced ? (
                      <td colSpan={3} className={`${CELL} text-right text-[12.5px] text-ink/45`}>
                        {UNPRICED}
                      </td>
                    ) : bySize ? (
                      row.by_source_size.map((cost, index) => (
                        <td key={index} className={NUM_CELL}>
                          {formatKrw(cost.krw, row.open_ended)}
                        </td>
                      ))
                    ) : (
                      <>
                        <td className={NUM_CELL}>
                          {row.per_attempt ? formatKrw(row.per_attempt.krw, row.open_ended) : "—"}
                        </td>
                        <td className={NUM_CELL}>
                          {row.per_problem_krw && estimate.participant_count > 0
                            ? formatKrw(row.per_problem_krw, row.open_ended)
                            : "—"}
                        </td>
                        <td className={NUM_CELL}>{ratioText(row)}</td>
                      </>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="px-3.5 py-2.5 text-[11.5px] leading-relaxed text-ink/45">
          {bySize
            ? `채점은 시도 하나에 한 번이고, 비용은 제출 소스의 길이에 거의 비례합니다. 참여자가 내기 시작하면 이 클래스의 실제 평균으로 바뀝니다. ${BILLING_NOTE}`
            : `채점은 시도 하나에 한 번입니다. 「문제 하나」는 참여자 ${estimate.participant_count}명이 한 사람당 ${formatAttemptsPerParticipant(estimate.attempts_per_participant)} 낸다고 보고 셈했습니다. ${BILLING_NOTE} 추론 모델은 문제와 소스에 따라 크게 달라집니다.`}
        </p>
      </div>

      {isReasoning && current.priced && current.ratio_to_baseline !== null ? (
        <div data-testid="class-scoring-cost-reasoning-warning" className="flex flex-col gap-1 border border-attention bg-surface px-3.5 py-3">
          <strong className="text-[13px] font-semibold text-attention">
            추론 모델은 시도 1건이 {estimate.baseline_model_id}의 약 {formatRatio(current.ratio_to_baseline)}입니다
          </strong>
          <span className="text-[12.5px] leading-relaxed text-ink/75">
            체크리스트가 「코드에 이것이 있는가」를 묻는 문제라면 {estimate.baseline_model_id}로도 대개 같은 판정이
            나옵니다. 판정이 어려운 문제만 문제 설정에서 따로 고르세요.
          </span>
        </div>
      ) : null}
    </div>
  );
}

/** 예산 칸 아래 한 줄 — 「이 한도면 시도 약 N건」. */
export function BudgetAttemptsHint({
  state,
  modelId,
  reasoningEffort,
  budgetText,
}: {
  state: ScoringCostState;
  modelId: string;
  reasoningEffort: string;
  budgetText: string;
}) {
  if (state.status !== "ready") return null;
  const row = findCostRow(state.estimate, modelId, reasoningEffort);
  const attempts = attemptsWithinBudget(budgetText, row);
  if (attempts === null) return null;
  const count = attempts.toLocaleString("ko-KR");
  return (
    <span data-testid="token-budget-attempts-hint" className="text-[11.5px] leading-relaxed text-ink/45">
      {state.estimate.basis === "source_sizes"
        ? `소스가 5만 자 안팎이면 시도 약 ${count}건을 채점합니다(지금 설정 기준).`
        : `이 한도면 시도 약 ${count}건을 채점합니다(지금 설정 기준).`}
    </span>
  );
}

function CostCell({ label, value, tone, last }: { label: string; value: string; tone?: string; last?: boolean }) {
  return (
    <div className={`flex min-w-0 flex-col gap-1 px-3.5 py-3 ${last ? "" : "border-b border-rule @[420px]:border-b-0 @[420px]:border-r"}`}>
      <span className="text-[11.5px] text-ink/45">{label}</span>
      <strong className={`font-mono text-[18px] font-medium ${tone ?? ""}`}>{value}</strong>
    </div>
  );
}

export function ProblemScoringCost({
  state,
  testIdPrefix,
  modelId,
  reasoningEffort,
  isReasoning,
  selectableModelIds,
  onUseBaseline,
}: {
  state: ScoringCostState;
  testIdPrefix: string;
  /** 이 문제가 실제로 쓸 모델·추론 강도(「클래스 기본값」을 풀어 넣은 값). */
  modelId: string;
  reasoningEffort: string;
  isReasoning: boolean;
  /** 이 키로 고를 수 있는 모델 — 기준 모델(gpt-4.1-mini)이 없으면 바꾸기 버튼을 보이지 않는다. */
  selectableModelIds: string[];
  onUseBaseline: () => void;
}) {
  if (state.status !== "ready") return null;
  const { estimate } = state;
  const row = findCostRow(estimate, modelId, reasoningEffort);
  const baseline = findCostRow(estimate, estimate.baseline_model_id, "");
  const bySize = estimate.basis === "source_sizes";
  const isBaseline = modelId === estimate.baseline_model_id;

  let cells: { label: string; value: string; tone?: string }[];
  if (!row || !row.priced) {
    cells = [];
  } else if (bySize) {
    cells = estimate.source_size_bands.map((chars, index) => ({
      label: index === 0 ? `시도 1건 · 소스 약 ${formatManCount(chars)} 자` : `시도 1건 · 약 ${formatManCount(chars)} 자`,
      value: row.by_source_size[index] ? formatKrw(row.by_source_size[index].krw, row.open_ended) : "—",
    }));
  } else {
    cells = [
      { label: "시도 1건", value: row.per_attempt ? formatKrw(row.per_attempt.krw, row.open_ended) : "—" },
      {
        label: `참여자 ${estimate.participant_count}명 · 1인 ${formatAttemptsPerParticipant(estimate.attempts_per_participant)}`,
        value:
          row.per_problem_krw && estimate.participant_count > 0 ? formatKrw(row.per_problem_krw, row.open_ended) : "—",
      },
      {
        label: `${estimate.baseline_model_id} 대비`,
        value: ratioText(row),
        tone: isBaseline ? "text-verified" : isReasoning ? "text-attention" : "",
      },
    ];
  }

  let cheaperText: string | null = null;
  if (!isBaseline && selectableModelIds.includes(estimate.baseline_model_id) && baseline && baseline.priced) {
    if (bySize) {
      const middle = baseline.by_source_size[1];
      cheaperText = middle
        ? `${estimate.baseline_model_id}로 채점하면 소스 5만 자 시도 1건이 ${formatKrw(middle.krw)}입니다.`
        : null;
    } else if (baseline.per_attempt) {
      cheaperText =
        baseline.per_problem_krw && estimate.participant_count > 0
          ? `${estimate.baseline_model_id}로 채점하면 시도 1건 ${formatKrw(baseline.per_attempt.krw)}, 이 문제 전체 ${formatKrw(baseline.per_problem_krw)}입니다.`
          : `${estimate.baseline_model_id}로 채점하면 시도 1건 ${formatKrw(baseline.per_attempt.krw)}입니다.`;
    }
  }

  return (
    <div data-testid={`${testIdPrefix}-scoring-cost`} className="@container mt-1 border border-rule">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-rule px-3.5 py-3">
        <h3 className="text-[13.5px] font-semibold">이 문제의 예상 채점 비용</h3>
        <span data-testid={`${testIdPrefix}-scoring-cost-basis`} className="text-[11.5px] text-ink/45">
          {costBasisText(estimate, "problem")}
        </span>
      </div>
      {cells.length > 0 ? (
        <div className="grid grid-cols-1 @[420px]:grid-cols-3">
          {cells.map((cell, index) => (
            <CostCell key={cell.label} {...cell} last={index === cells.length - 1} />
          ))}
        </div>
      ) : (
        <p data-testid={`${testIdPrefix}-scoring-cost-unpriced`} className="px-3.5 py-3 text-[13px] text-ink/60">
          {costRowLabel({ model_id: modelId, reasoning_effort: isReasoning ? reasoningEffort : null })} · {UNPRICED}
        </p>
      )}
      {cheaperText ? (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-rule bg-paper px-3.5 py-3">
          <span className="text-[12.5px] leading-relaxed text-ink/75">{cheaperText}</span>
          <button
            type="button"
            data-testid={`${testIdPrefix}-use-baseline-model`}
            onClick={onUseBaseline}
            className={buttonClass("secondary", "sm")}
          >
            {estimate.baseline_model_id}로 바꾸기
          </button>
        </div>
      ) : null}
      <p className="border-t border-rule px-3.5 py-2.5 text-[11.5px] leading-relaxed text-ink/45">
        체크리스트 전부를 시도 하나에 한 번에 판정합니다. 소스가 길수록, 추론 강도가 높을수록 비용이 커집니다.{" "}
        {BILLING_NOTE}
      </p>
    </div>
  );
}
