// 예상 채점 비용 (#591) — 셈은 백엔드(`classroom.scoring_cost`)가 하고, 화면은 고른
// 모델·강도의 줄을 찾아 원화·배율을 사람 말로 적기만 한다. 여기 있는 것은 그 찾기와
// 적기다 — 단가·토큰 어림을 화면에 따로 두지 않는다.
//
// 호환 서버 클래스(`unit` 이 tokens, #604)는 단가를 몰라 원화·배율이 없다 — 지금 설정만
// 토큰으로 온다(`krw` 는 null).

// 원화는 OpenAI 키 클래스만 — 호환 서버는 null.
export type ScoringCostAttempt = { krw: number | null; tokens: number };

export type ScoringCostRow = {
  model_id: string;
  // 추론 모델이면 low·medium·high, 아니면 null.
  reasoning_effort: string | null;
  // 거짓이면 단가를 몰라 「비용 미확인」이다.
  priced: boolean;
  // 위로 열린 어림(추론 강도 높음) — 「약 N원~」.
  open_ended: boolean;
  // 이 문제·클래스 평균 길이에서 시도 1건. 소스 크기별 기준이면 null.
  per_attempt: ScoringCostAttempt | null;
  per_problem_krw: number | null;
  // 같은 셈을 토큰으로 — 호환 서버(unit tokens)일 때만.
  per_problem_tokens: number | null;
  ratio_to_baseline: number | null;
  // `source_size_bands` 순서의 시도 1건.
  by_source_size: ScoringCostAttempt[];
};

export type ScoringCostEstimate = {
  // krw — OpenAI 단가로 원화, tokens — 호환 서버라 단가를 몰라 토큰만.
  unit: "krw" | "tokens";
  basis: "problem" | "class" | "source_sizes";
  sample_count: number;
  avg_prompt_chars: number | null;
  avg_input_tokens: number | null;
  participant_count: number;
  attempts_per_participant: number;
  attempts_per_participant_measured: boolean;
  source_size_bands: number[];
  baseline_model_id: string;
  krw_per_usd: number;
  rows: ScoringCostRow[];
};

const EFFORT_LABEL: Record<string, string> = { low: "낮음", medium: "보통", high: "높음" };

/** 고른 모델·강도의 줄 — 추론 모델이 아니면 강도는 보지 않는다. 없으면 「비용 미확인」이다. */
export function findCostRow(
  estimate: ScoringCostEstimate,
  modelId: string,
  reasoningEffort: string,
): ScoringCostRow | null {
  return (
    estimate.rows.find(
      (row) =>
        row.model_id === modelId &&
        (row.reasoning_effort === null || row.reasoning_effort === reasoningEffort),
    ) ?? null
  );
}

export function costRowLabel(row: Pick<ScoringCostRow, "model_id" | "reasoning_effort">): string {
  return row.reasoning_effort === null
    ? row.model_id
    : `${row.model_id} · 추론 ${EFFORT_LABEL[row.reasoning_effort] ?? row.reasoning_effort}`;
}

// 100원 아래는 원 단위, 1만 원 아래는 유효숫자 둘, 그 위는 100원 단위 — 어림이라 끝자리를
// 보이지 않는다.
function roundKrw(krw: number): number {
  if (krw < 100) return Math.max(1, Math.round(krw));
  if (krw < 10_000) {
    const step = 10 ** (Math.floor(Math.log10(krw)) - 1);
    return Math.round(krw / step) * step;
  }
  return Math.round(krw / 100) * 100;
}

export function formatKrw(krw: number | null, openEnded = false): string {
  if (krw === null) return "—";
  return `약 ${roundKrw(krw).toLocaleString("ko-KR")}원${openEnded ? "~" : ""}`;
}

export function formatRatio(ratio: number, openEnded = false): string {
  const rounded = ratio < 10 ? Math.round(ratio * 10) / 10 : Math.round(ratio);
  return `${rounded.toLocaleString("ko-KR")}배${openEnded ? "~" : ""}`;
}

// 5.5만 자 · 1.7만 토큰처럼 만 단위로 줄여 적는다.
export function formatManCount(count: number): string {
  if (count < 10_000) return count.toLocaleString("ko-KR");
  const man = Math.round(count / 1_000) / 10;
  return `${man.toLocaleString("ko-KR")}만`;
}

export function formatTokens(tokens: number, openEnded = false): string {
  return `약 ${formatManCount(tokens)} 토큰${openEnded ? "~" : ""}`;
}

export function sourceBandLabel(chars: number): string {
  return `소스 약 ${formatManCount(chars)} 자`;
}

/** 표 머리의 한 줄 — 무엇을 기준으로 셈했는지. */
export function costBasisText(estimate: ScoringCostEstimate, scope: "class" | "problem"): string {
  const size =
    estimate.avg_prompt_chars !== null && estimate.avg_input_tokens !== null
      ? `소스 약 ${formatManCount(estimate.avg_prompt_chars)} 자(입력 약 ${formatManCount(estimate.avg_input_tokens)} 토큰)`
      : "";
  if (estimate.basis === "problem") return `이 문제 시도 ${estimate.sample_count}건 평균 · ${size}`;
  if (estimate.basis === "class") {
    return scope === "problem"
      ? `이 문제는 아직 시도가 없어 클래스 평균으로 셈했습니다 · ${size}`
      : `이 클래스 시도 평균 · ${size}`;
  }
  return "이 클래스에 아직 시도가 없어 소스 크기별로 셈했습니다";
}

export function formatAttemptsPerParticipant(n: number): string {
  return `${(Math.round(n * 10) / 10).toLocaleString("ko-KR")}번`;
}

/** 시도 1건이 쓰는 토큰 — 기준이 소스 크기별이면 「보통」(가운데) 크기로 본다. */
export function tokensPerAttempt(row: ScoringCostRow): number | null {
  if (row.per_attempt) return row.per_attempt.tokens;
  const middle = row.by_source_size[Math.floor(row.by_source_size.length / 2)];
  return middle ? middle.tokens : null;
}

/** 예산(토큰)으로 채점할 수 있는 시도 수 — 예산 칸이 비었거나 셈할 수 없으면 null. */
export function attemptsWithinBudget(budgetText: string, row: ScoringCostRow | null): number | null {
  const budget = Number(budgetText);
  if (!row || budgetText.trim() === "" || !Number.isFinite(budget) || budget <= 0) return null;
  const tokens = tokensPerAttempt(row);
  if (!tokens) return null;
  return Math.floor(budget / tokens);
}
