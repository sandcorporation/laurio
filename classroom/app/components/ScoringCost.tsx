"use client";

// 예상 채점 비용 (#591) — 강사가 모델·추론 강도를 고르는 바로 그 자리에서 시도 하나와 문제
// 하나가 얼마인지 보인다. 「클래스 설정」의 기본 모델 표(#636)는 `settings/model-table.tsx` 가 같은 비용을 줄마다 적고, 「문제 설정 › 채점 모델」은
// 이 문제가 실제로 쓸 설정 한 줄을 보인다. 값은 서버가 셈한 것(`useScoringCost`)이고, 이
// 파일은 고른 모델·강도의 줄을 찾아 적기만 한다(`lib/scoring/cost.ts`).
import { Badge, buttonClass } from "@/app/components/ui";
import {
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
import type { ScoringCostState } from "@/lib/scoring/use-scoring-cost";

const BILLING_NOTE = "실제 청구액은 OpenAI 사용량 화면이 기준입니다.";
// 호환 서버(#604) — 단가를 몰라 토큰으로만 보인다.
const TOKEN_NOTE =
  "호환 서버는 단가를 알 수 없어 토큰으로만 셈합니다. 사용량도 토큰으로 세고, 서버가 사용량을 알려 주지 않으면 프롬프트 길이로 어림해 셉니다.";
const BAND_NAMES = ["작은 과제", "보통", "큰 프로젝트"];
const UNPRICED = "비용 미확인";

function ratioText(row: ScoringCostRow): string {
  return row.ratio_to_baseline === null ? "—" : formatRatio(row.ratio_to_baseline, row.open_ended);
}

function CurrentBadge() {
  return (
    <span className="ml-2 inline-flex shrink-0">
      <Badge>지금 설정</Badge>
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
