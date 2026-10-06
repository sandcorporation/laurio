import { describe, expect, it } from "vitest";

import {
  attemptsWithinBudget,
  costBasisText,
  costRowLabel,
  findCostRow,
  formatKrw,
  formatManCount,
  formatRatio,
  type ScoringCostEstimate,
  type ScoringCostRow,
} from "./cost";

function row(partial: Partial<ScoringCostRow>): ScoringCostRow {
  return {
    model_id: "gpt-4.1-mini",
    reasoning_effort: null,
    priced: true,
    open_ended: false,
    per_attempt: null,
    per_problem_krw: null,
    ratio_to_baseline: 1,
    by_source_size: [],
    ...partial,
  };
}

function estimate(partial: Partial<ScoringCostEstimate>): ScoringCostEstimate {
  return {
    basis: "class",
    sample_count: 40,
    avg_prompt_chars: 55_000,
    avg_input_tokens: 16_667,
    participant_count: 18,
    attempts_per_participant: 2.5,
    attempts_per_participant_measured: false,
    source_size_bands: [10_000, 50_000, 200_000],
    baseline_model_id: "gpt-4.1-mini",
    krw_per_usd: 1380,
    rows: [],
    ...partial,
  };
}

describe("예상 채점 비용 적기 (#591)", () => {
  it("원화는 어림으로 — 끝자리를 보이지 않는다", () => {
    expect(formatKrw(14.7)).toBe("약 15원");
    expect(formatKrw(677)).toBe("약 680원");
    expect(formatKrw(3_386)).toBe("약 3,400원");
    expect(formatKrw(19_362)).toBe("약 19,400원");
    expect(formatKrw(738, true)).toBe("약 740원~");
  });

  it("배율은 10배 아래만 소수 하나", () => {
    expect(formatRatio(1)).toBe("1배");
    expect(formatRatio(5.04)).toBe("5배");
    expect(formatRatio(1.43)).toBe("1.4배");
    expect(formatRatio(28.9)).toBe("29배");
    expect(formatRatio(50.2, true)).toBe("50배~");
  });

  it("만 단위로 줄여 적는다", () => {
    expect(formatManCount(55_000)).toBe("5.5만");
    expect(formatManCount(16_667)).toBe("1.7만");
    expect(formatManCount(200_000)).toBe("20만");
    expect(formatManCount(8_000)).toBe("8,000");
  });

  it("추론 모델은 강도까지 맞는 줄을, 아니면 강도와 상관없이 그 모델의 줄을 찾는다", () => {
    const rows = [
      row({ model_id: "gpt-4.1-mini" }),
      row({ model_id: "gpt-5.5", reasoning_effort: "low" }),
      row({ model_id: "gpt-5.5", reasoning_effort: "medium" }),
    ];
    const e = estimate({ rows });
    expect(findCostRow(e, "gpt-4.1-mini", "medium")).toBe(rows[0]);
    expect(findCostRow(e, "gpt-5.5", "medium")).toBe(rows[2]);
    expect(findCostRow(e, "gpt-4o", "low")).toBeNull();
    expect(costRowLabel(rows[2])).toBe("gpt-5.5 · 추론 보통");
    expect(costRowLabel(rows[0])).toBe("gpt-4.1-mini");
  });

  it("어느 기준으로 셈했는지 말한다", () => {
    expect(costBasisText(estimate({ basis: "problem", sample_count: 23 }), "problem")).toBe(
      "이 문제 시도 23건 평균 · 소스 약 5.5만 자(입력 약 1.7만 토큰)",
    );
    expect(costBasisText(estimate({}), "problem")).toBe(
      "이 문제는 아직 시도가 없어 클래스 평균으로 셈했습니다 · 소스 약 5.5만 자(입력 약 1.7만 토큰)",
    );
    expect(costBasisText(estimate({}), "class")).toBe("이 클래스 시도 평균 · 소스 약 5.5만 자(입력 약 1.7만 토큰)");
    expect(
      costBasisText(estimate({ basis: "source_sizes", avg_prompt_chars: null, avg_input_tokens: null }), "class"),
    ).toBe("이 클래스에 아직 시도가 없어 소스 크기별로 셈했습니다");
  });

  it("예산 칸의 토큰을 시도 1건의 토큰으로 나눈다 — 소스 크기별이면 가운데 크기로", () => {
    const measured = row({ per_attempt: { krw: 15, tokens: 20_000 } });
    expect(attemptsWithinBudget("500000", measured)).toBe(25);
    const bySize = row({
      by_source_size: [
        { krw: 8, tokens: 5_500 },
        { krw: 14, tokens: 17_650 },
        { krw: 40, tokens: 63_000 },
      ],
    });
    expect(attemptsWithinBudget("176500", bySize)).toBe(10);
    expect(attemptsWithinBudget("", measured)).toBeNull();
    expect(attemptsWithinBudget("500000", null)).toBeNull();
  });
});
