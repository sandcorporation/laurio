"use client";

// 예상 채점 비용 (#591) — 강사가 모델·추론 강도를 고르는 바로 그 자리에서 시도 하나와 문제
// 하나가 얼마인지 보인다. 「클래스 설정 › 채점」은 모델별 표를, 「문제 설정 › 채점 모델」은
// 이 문제가 실제로 쓸 설정 한 줄을 보인다. 값은 서버가 셈한 것(`useScoringCost`)이고, 이
// 파일은 고른 모델·강도의 줄을 찾아 적기만 한다(`lib/scoring/cost.ts`).
import { useEffect, useId, useState } from "react";

import { Badge, buttonClass } from "@/app/components/ui";
import {
  classCostSummary,
  costBasisText,
  costRowLabel,
  findCostRow,
  formatAttemptsPerParticipant,
  formatKrw,
  formatManCount,
  formatRatio,
  formatTokens,
  problemCostLine,
  type ScoringCostEstimate,
  type ScoringCostRow,
} from "@/lib/scoring/cost";
import { readCostTableOpen, writeCostTableOpen } from "@/lib/scoring/cost-table-open";
import type { ScoringCostState } from "@/lib/scoring/use-scoring-cost";

const BILLING_NOTE = "실제 청구액은 OpenAI 사용량 화면이 기준입니다.";
// 호환 서버(#604) — 단가를 몰라 토큰으로만 보인다.
const TOKEN_NOTE =
  "호환 서버는 단가를 알 수 없어 토큰으로만 셈합니다. 사용량도 토큰으로 세고, 서버가 사용량을 알려 주지 않으면 프롬프트 길이로 어림해 셉니다.";
const BAND_NAMES = ["작은 과제", "보통", "큰 프로젝트"];
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

// 표의 줄: 이 키로 쓸 수 있는 모델 전부(카탈로그 순서, #617). 표가 길어 지금 고른 설정은 맨 위로
// 올린다 — 서버 줄에 없으면(아직 저장하지 않은 선택) 「비용 미확인」 한 줄로.
function tableRows(
  estimate: ScoringCostEstimate,
  modelId: string,
  reasoningEffort: string,
  isReasoning: boolean,
): { rows: ScoringCostRow[]; current: ScoringCostRow } {
  const found = findCostRow(estimate, modelId, reasoningEffort);
  const current: ScoringCostRow = found ?? {
    model_id: modelId,
    reasoning_effort: isReasoning ? reasoningEffort : null,
    priced: false,
    open_ended: false,
    per_attempt: null,
    per_problem_krw: null,
    per_problem_tokens: null,
    ratio_to_baseline: null,
    by_source_size: [],
  };
  return { rows: [current, ...estimate.rows.filter((row) => row !== found)], current };
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
  // 표는 길어(#617) 기본은 접어 두고 머리줄에 지금 설정의 시도 1건만 보인다(#619). 펼친 상태는
  // 그 브라우저가 기억한다 — 서버 렌더와 어긋나지 않게 첫 그림은 접힘, 붙은 뒤에 읽는다.
  const [open, setOpen] = useState(false);
  const panelId = useId();
  useEffect(() => {
    setOpen(readCostTableOpen(browserStorage()));
  }, []);
  function toggle() {
    const next = !open;
    setOpen(next);
    writeCostTableOpen(browserStorage(), next);
  }

  if (state.status !== "ready") return null;
  const { estimate } = state;
  if (estimate.unit === "tokens") {
    return (
      <TokenEstimate
        estimate={estimate}
        modelId={modelId}
        scope="class"
        testIdPrefix="class"
        title="예상 채점 사용량"
      />
    );
  }
  const { rows, current } = tableRows(estimate, modelId, reasoningEffort, isReasoning);
  const bySize = estimate.basis === "source_sizes";
  // 참여자가 없으면 「문제 하나」 칸을 뺀다 — 0명으로 곱한 값은 뜻이 없다(#617).
  const hasParticipants = estimate.participant_count > 0;
  const isCurrent = (row: ScoringCostRow) =>
    row.model_id === current.model_id && row.reasoning_effort === current.reasoning_effort;

  return (
    <div className="flex flex-col gap-3">
      <div data-testid="class-scoring-cost" className="border border-rule">
        <h3>
          <button
            type="button"
            data-testid="class-scoring-cost-toggle"
            aria-expanded={open}
            aria-controls={panelId}
            onClick={toggle}
            className={`flex w-full items-start justify-between gap-3 px-3.5 py-3 text-left ${open ? "border-b border-rule" : ""}`}
          >
            <span className="flex min-w-0 flex-col gap-1">
              <span className="text-[13.5px] font-semibold">모델별 예상 채점 비용</span>
              <span data-testid="class-scoring-cost-summary" className="text-[13px]">
                {classCostSummary(estimate, current)}
              </span>
              <span data-testid="class-scoring-cost-basis" className="text-[11.5px] text-ink/45">
                {costBasisText(estimate, "class")}
              </span>
            </span>
            <span className="shrink-0 whitespace-nowrap text-[12px] text-ink/45">
              {open ? "접기" : `모델 ${rows.length}개 펼치기`}
            </span>
          </button>
        </h3>
        <div id={panelId} hidden={!open} data-testid="class-scoring-cost-panel">
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
                      ...(hasParticipants
                        ? ([
                            [
                              `문제 하나 · ${estimate.participant_count}명`,
                              row.per_problem_krw ? formatKrw(row.per_problem_krw, row.open_ended) : "—",
                            ],
                          ] as [string, string][])
                        : []),
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
                      {hasParticipants ? (
                        <th className={`${HEAD_CELL} text-right font-normal`}>
                          문제 하나 · {estimate.participant_count}명
                        </th>
                      ) : null}
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
                        <td colSpan={bySize ? estimate.source_size_bands.length : hasParticipants ? 3 : 2} className={`${CELL} text-right text-[12.5px] text-ink/45`}>
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
                          {hasParticipants ? (
                            <td className={NUM_CELL}>
                              {row.per_problem_krw ? formatKrw(row.per_problem_krw, row.open_ended) : "—"}
                            </td>
                          ) : null}
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
              ? `채점은 시도 하나에 한 번이고, 비용은 제출 소스의 길이에 거의 비례합니다. 시도가 ${estimate.min_sample_count}건 쌓이면 이 클래스의 실제 평균으로 바뀝니다. ${BILLING_NOTE}`
              : hasParticipants
                ? `채점은 시도 하나에 한 번입니다. 「문제 하나」는 참여자 ${estimate.participant_count}명이 한 사람당 ${formatAttemptsPerParticipant(estimate.attempts_per_participant)} 낸다고 보고 셈했습니다. ${BILLING_NOTE} 추론 모델은 문제와 소스에 따라 크게 달라집니다.`
                : `채점은 시도 하나에 한 번입니다. 문제 하나의 비용은 참여자가 들어오면 보입니다. ${BILLING_NOTE} 추론 모델은 문제와 소스에 따라 크게 달라집니다.`}
          </p>
        </div>
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

function browserStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
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
  if (estimate.unit === "tokens") {
    return (
      <TokenEstimate
        estimate={estimate}
        modelId={modelId}
        scope="problem"
        testIdPrefix={testIdPrefix}
        title="이 문제의 예상 채점 사용량"
      />
    );
  }
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
      // 참여자가 없으면 이 칸을 뺀다 — 0명으로 곱한 값은 뜻이 없다(#617).
      ...(estimate.participant_count > 0
        ? [
            {
              label: `참여자 ${estimate.participant_count}명 · 1인 ${formatAttemptsPerParticipant(estimate.attempts_per_participant)}`,
              value: row.per_problem_krw ? formatKrw(row.per_problem_krw, row.open_ended) : "—",
            },
          ]
        : []),
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
        <div className={`grid grid-cols-1 ${cells.length === 3 ? "@[420px]:grid-cols-3" : "@[420px]:grid-cols-2"}`}>
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

/** 호환 서버 클래스(#604) — 원화·배율·「더 싼 모델로 바꾸기」 없이 지금 설정의 토큰만. */
function TokenEstimate({
  estimate,
  modelId,
  scope,
  testIdPrefix,
  title,
}: {
  estimate: ScoringCostEstimate;
  modelId: string;
  scope: "class" | "problem";
  testIdPrefix: string;
  title: string;
}) {
  // 토큰 어림은 모델 이름이 아니라 실을 추론 강도로만 갈린다 — 아직 저장하지 않은 모델을 골라도
  // 지금 설정의 줄로 보인다.
  const row = estimate.rows.find((candidate) => candidate.model_id === modelId) ?? estimate.rows[0] ?? null;
  let cells: { label: string; value: string }[] = [];
  if (row && estimate.basis === "source_sizes") {
    cells = estimate.source_size_bands.map((chars, index) => ({
      label: `시도 1건 · ${BAND_NAMES[index] ?? ""} · 소스 약 ${formatManCount(chars)} 자`,
      value: row.by_source_size[index] ? formatTokens(row.by_source_size[index].tokens, row.open_ended) : "—",
    }));
  } else if (row) {
    cells = [
      { label: "시도 1건", value: row.per_attempt ? formatTokens(row.per_attempt.tokens, row.open_ended) : "—" },
      {
        label: `문제 하나 · 참여자 ${estimate.participant_count}명 · 1인 ${formatAttemptsPerParticipant(estimate.attempts_per_participant)}`,
        value:
          row.per_problem_tokens && estimate.participant_count > 0
            ? formatTokens(row.per_problem_tokens, row.open_ended)
            : "—",
      },
    ];
  }
  return (
    <div data-testid={`${testIdPrefix}-scoring-cost`} className="@container mt-1 border border-rule">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-rule px-3.5 py-3">
        <h3 className="text-[13.5px] font-semibold">{title}</h3>
        <span data-testid={`${testIdPrefix}-scoring-cost-basis`} className="text-[11.5px] text-ink/45">
          {costBasisText(estimate, scope)}
        </span>
      </div>
      <div className="flex flex-wrap items-center border-b border-rule px-3.5 py-2.5 text-[13px]">
        <span className="font-semibold">{modelId}</span>
        <CurrentBadge />
      </div>
      {cells.length > 0 ? (
        <div className={`grid grid-cols-1 ${cells.length === 3 ? "@[420px]:grid-cols-3" : "@[420px]:grid-cols-2"}`}>
          {cells.map((cell, index) => (
            <CostCell key={cell.label} {...cell} last={index === cells.length - 1} />
          ))}
        </div>
      ) : null}
      <p
        data-testid={`${testIdPrefix}-scoring-cost-token-note`}
        className="border-t border-rule px-3.5 py-2.5 text-[11.5px] leading-relaxed text-ink/45"
      >
        {TOKEN_NOTE}
      </p>
    </div>
  );
}

/** 문제 편집의 채점 모델 카드 한 줄(#637) — 이 문제가 실제로 쓸 설정의 시도 1건과 문제 하나. */
export function ProblemCostLine({
  state,
  testIdPrefix,
  modelId,
  reasoningEffort,
}: {
  state: ScoringCostState;
  testIdPrefix: string;
  modelId: string;
  reasoningEffort: string;
}) {
  if (state.status !== "ready") return null;
  const { estimate } = state;
  const row =
    estimate.unit === "tokens"
      ? (estimate.rows.find((candidate) => candidate.model_id === modelId) ?? estimate.rows[0] ?? null)
      : findCostRow(estimate, modelId, reasoningEffort);
  const line = problemCostLine(estimate, row);
  return (
    <p data-testid={`${testIdPrefix}-scoring-cost`} className="border-t border-rule pt-3 text-[12.5px] text-ink/75">
      {line ?? `${modelId} · ${UNPRICED}`}
    </p>
  );
}
