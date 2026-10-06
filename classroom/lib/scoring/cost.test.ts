import { describe, expect, it } from "vitest";

import {
  attemptsWithinBudget,
  classCostSummary,
  costBasisText,
  costRowLabel,
  findCostRow,
  formatKrw,
  formatManCount,
  formatRatio,
  formatTokens,
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
    per_problem_tokens: null,
    ratio_to_baseline: 1,
    by_source_size: [],
    ...partial,
  };
}

function estimate(partial: Partial<ScoringCostEstimate>): ScoringCostEstimate {
  return {
    unit: "krw",
    basis: "class",
    sample_count: 40,
    min_sample_count: 3,
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
      "이 문제는 시도가 3건 미만이라 클래스 시도 40건 평균으로 셈했습니다 · 소스 약 5.5만 자(입력 약 1.7만 토큰)",
    );
    expect(costBasisText(estimate({}), "class")).toBe("이 클래스 시도 40건 평균 · 소스 약 5.5만 자(입력 약 1.7만 토큰)");
    const bySize = { basis: "source_sizes", avg_prompt_chars: null, avg_input_tokens: null } as const;
    expect(costBasisText(estimate({ ...bySize, sample_count: 0 }), "class")).toBe(
      "이 클래스에 아직 시도가 없어 소스 크기별로 셈했습니다",
    );
    // 시험 삼아 낸 몇 건으로 평균을 내지 않는다(#617) — 그 기준을 말한다.
    expect(costBasisText(estimate({ ...bySize, sample_count: 2 }), "problem")).toBe(
      "이 클래스 시도가 2건뿐이라 소스 크기별로 셈했습니다 · 평균은 3건부터 냅니다",
    );
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

describe("호환 서버 — 토큰으로 (#604)", () => {
  it("토큰은 만 단위로 줄여 「약 N만 토큰」으로 적는다", () => {
    expect(formatTokens(18_652)).toBe("약 1.9만 토큰");
    expect(formatTokens(5_530)).toBe("약 5,530 토큰");
    expect(formatTokens(22_500, true)).toBe("약 2.3만 토큰~");
  });

  it("토큰 줄은 강도가 이미 풀려 있어 모델로 찾고, 예산 안 시도 수도 그 토큰으로 센다", () => {
    const tokenRow = row({
      priced: false,
      ratio_to_baseline: null,
      per_attempt: { krw: null, tokens: 20_000 },
      per_problem_tokens: 900_000,
    });
    const found = findCostRow(estimate({ unit: "tokens", rows: [tokenRow] }), "gpt-4.1-mini", "medium");
    expect(found).toBe(tokenRow);
    expect(attemptsWithinBudget("1000000", found)).toBe(50);
  });
});

describe("접힌 비용 표의 머리줄 (#619)", () => {
  it("지금 설정의 시도 1건 비용을 한 줄로 — 추론 모델은 강도까지", () => {
    expect(classCostSummary(estimate({}), row({ model_id: "gpt-4o-mini", per_attempt: { krw: 3.2, tokens: 19_000 } }))).toBe(
      "지금 설정 gpt-4o-mini · 시도 1건 약 3원",
    );
    expect(
      classCostSummary(
        estimate({}),
        row({ model_id: "gpt-5.1", reasoning_effort: "high", open_ended: true, per_attempt: { krw: 212, tokens: 31_000 } }),
      ),
    ).toBe("지금 설정 gpt-5.1 · 추론 높음 · 시도 1건 약 210원~");
  });

  it("소스 크기별이면 가운데 크기로, 단가가 없으면 「비용 미확인」", () => {
    const bySize = row({
      by_source_size: [
        { krw: 8, tokens: 5_500 },
        { krw: 14, tokens: 17_650 },
        { krw: 40, tokens: 63_000 },
      ],
    });
    expect(classCostSummary(estimate({ basis: "source_sizes" }), bySize)).toBe(
      "지금 설정 gpt-4.1-mini · 소스 약 5만 자면 시도 1건 약 14원",
    );
    expect(classCostSummary(estimate({}), row({ model_id: "o3", priced: false, ratio_to_baseline: null }))).toBe(
      "지금 설정 o3 · 비용 미확인",
    );
  });
});
