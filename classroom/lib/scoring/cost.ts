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
  // 거짓이면 단가를 몰라 「단가 모름」이다.
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
  // 그 기준의 시도 수 — source_sizes 면 클래스 시도 수(평균을 내기에 모자란 수).
  sample_count: number;
  // 평균을 낼 최소 시도 수 — 이보다 적으면 다음 기준으로 내려간다(#617).
  min_sample_count: number;
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

/** 고른 모델·강도의 줄 — 추론 모델이 아니면 강도는 보지 않는다. 없으면 「단가 모름」이다. */
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

/** 단가표에 없는 모델의 비용을 부르는 한 이름(#797) — 호환 서버의 「토큰만」(#604)과 섞지 않는다. */
export const UNPRICED_TEXT = "단가 모름";

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
  const n = estimate.sample_count;
  const min = estimate.min_sample_count;
  if (estimate.basis === "problem") return `이 문제 시도 ${n}건 평균 · ${size}`;
  if (estimate.basis === "class") {
    return scope === "problem"
      ? `이 문제는 시도가 ${min}건 미만이라 클래스 시도 ${n}건 평균으로 셈했습니다 · ${size}`
      : `이 클래스 시도 ${n}건 평균 · ${size}`;
  }
  if (n === 0) return "이 클래스에 아직 시도가 없어 소스 크기별로 셈했습니다";
  return `이 클래스 시도가 ${n}건뿐이라 소스 크기별로 셈했습니다 · 평균은 ${min}건부터 냅니다`;
}

export function formatAttemptsPerParticipant(n: number): string {
  return `${(Math.round(n * 10) / 10).toLocaleString("ko-KR")}회`;
}

/** 시도 1건 — 기준이 소스 크기별이면 「보통」(가운데) 크기로 본다. */
function representativeAttempt(row: ScoringCostRow): ScoringCostAttempt | null {
  if (row.per_attempt) return row.per_attempt;
  return row.by_source_size[Math.floor(row.by_source_size.length / 2)] ?? null;
}

/**
 * 누적 사용량(토큰)의 원화 어림(#629) — 지금 설정(기본 모델·강도)의 토큰당 단가로 셈한다. 지난 시도가
 * 다른 모델이었어도 가리지 않는 어림이다. 단가를 모르면(호환 서버·단가 모름) null.
 */
export function usageKrw(tokens: number, row: ScoringCostRow | null): number | null {
  if (!row || !row.priced) return null;
  const attempt = representativeAttempt(row);
  if (!attempt || attempt.krw === null || attempt.tokens <= 0) return null;
  return Math.round((tokens * attempt.krw) / attempt.tokens);
}

/**
 * 누적 사용량 옆의 원화 칸(#797) — 토큰이 있는데 지금 모델의 단가를 모르면 비우지 않고
 * 「단가 모름 (모델 X)」로 낸다. 토큰이 없으면 null.
 */
export function usageCostText(tokens: number, row: ScoringCostRow | null, modelId: string): string | null {
  if (tokens <= 0) return null;
  const krw = usageKrw(tokens, row);
  if (krw === null) return `${UNPRICED_TEXT} (모델 ${modelId})`;
  return krw > 0 ? formatKrw(krw) : null;
}

/**
 * 접힌 「모델별 예상 채점 비용」 표의 머리줄(#619) — 펼치지 않아도 지금 설정의 시도 1건 비용이
 * 보인다. 기준이 소스 크기별이면 가운데(「보통」) 크기로 적는다.
 */
export function classCostSummary(estimate: ScoringCostEstimate, current: ScoringCostRow): string {
  const head = `지금 설정 ${costRowLabel(current)}`;
  if (!current.priced) return `${head} · ${UNPRICED_TEXT}`;
  if (current.per_attempt) return `${head} · 시도 1건 ${formatKrw(current.per_attempt.krw, current.open_ended)}`;
  const middle = Math.floor(current.by_source_size.length / 2);
  const cost = current.by_source_size[middle];
  const chars = estimate.source_size_bands[middle];
  if (!cost || chars === undefined) return `${head} · ${UNPRICED_TEXT}`;
  return `${head} · 소스 약 ${formatManCount(chars)} 자면 시도 1건 ${formatKrw(cost.krw, current.open_ended)}`;
}

/**
 * 문제 편집의 채점 모델 카드에 놓는 비용 한 줄(#637) — 「시도 1건 약 30원 · 참여자 24명 × 평균 1.6회 ≈ 약 1,150원」.
 * 기준이 소스 크기별이면 가운데(「보통」) 크기의 시도 1건만, 참여자가 없으면 시도 1건만 적는다.
 * 호환 서버(토큰 단위)는 같은 모양으로 토큰을 적는다. 단가를 모르면 null — 카드는 줄을 그리지 않는다.
 */
export function problemCostLine(estimate: ScoringCostEstimate, row: ScoringCostRow | null): string | null {
  if (!row) return null;
  const tokens = estimate.unit === "tokens";
  if (!tokens && !row.priced) return null;
  const attempt = representativeAttempt(row);
  if (!attempt) return null;
  const amount = (krw: number | null, tok: number) => (tokens ? formatTokens(tok, row.open_ended) : formatKrw(krw, row.open_ended));
  const head = `시도 1건 ${amount(attempt.krw, attempt.tokens)}`;
  const perProblem = tokens ? row.per_problem_tokens : row.per_problem_krw;
  if (estimate.participant_count <= 0 || !perProblem) return head;
  const whole = tokens ? formatTokens(perProblem, row.open_ended) : formatKrw(perProblem, row.open_ended);
  return `${head} · 참여자 ${estimate.participant_count}명 × 평균 ${formatAttemptsPerParticipant(estimate.attempts_per_participant)} ≈ ${whole}`;
}

/**
 * 기본 모델 표의 한 칸(#636) — 그 모델의 시도 1건 비용. 호환 서버(토큰 단위)는 토큰을, OpenAI 키는
 * 원화를 적고, 단가를 모르면 「단가 모름」이다. 기준이 소스 크기별이면 가운데(「보통」) 크기로 본다.
 */
export function modelCostCell(estimate: ScoringCostEstimate, row: ScoringCostRow | null): string {
  if (!row) return UNPRICED_TEXT;
  const attempt = representativeAttempt(row);
  if (estimate.unit === "tokens") return attempt ? formatTokens(attempt.tokens, row.open_ended) : UNPRICED_TEXT;
  if (!row.priced || !attempt) return UNPRICED_TEXT;
  return formatKrw(attempt.krw, row.open_ended);
}

