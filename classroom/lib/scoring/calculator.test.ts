import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { agentModelIds, calculatorPath, cheapestAgentModel, listedModels, capacityText, changeChoice, charsLabel, parseAssumption, submissionAmount, submissionBasis, type ScoringCalculator } from "./calculator";
import { formatKrw } from "./cost";

const SINGLE = {
  input_tokens: 1,
  output_tokens: 1,
  usd: 0.1,
  krw: 138,
  open_ended: false,
  fits: true,
  capacity_chars: 3_000_000,
  capacity_chars_hangul: 2_000_000,
  capacity_files: 1_875,
  capacity_files_hangul: 1_250,
  route: "single",
  seconds: 5,
  partial_krw: 138,
};
const NONE = { sample_count: 0, median: null, p90: null };

function calcOf(
  overrides: {
    method?: string;
    route?: string;
    staged?: boolean;
    agentKrw?: number | null;
    oversize?: { policy: string; agent_model: string; agent_krw: number | null };
  } = {},
): ScoringCalculator {
  const {
    method = "single",
    route = "single",
    staged = false,
    agentKrw = 400,
    oversize = { policy: "reject", agent_model: "", agent_krw: null },
  } = overrides;
  // 금액·크기 글자에 쓰는 칸만 채운 흉내
  return {
    selection: { model_id: "m", method },
    staged: { enabled: staged },
    oversize,
    rows: [
      {
        vendor: "openai",
        model_id: "m",
        single: { ...SINGLE, route },
        agent: { available: agentKrw !== null, krw: agentKrw, usd: 1, seconds: 1, measured_krw: NONE, measured_seconds: NONE },
      },
    ],
  } as unknown as ScoringCalculator;
}

describe("calculatorPath", () => {
  it("빈 칸은 싣지 않는다", () => {
    expect(calculatorPath(7, {})).toBe("/api/backend/classroom/classes/7/scoring-calculator");
  });
  it("고른 칸과 바꿔 본 가정을 쿼리로 싣는다", () => {
    expect(
      calculatorPath(7, { vendor: "anthropic", method: "agent", model: "claude-haiku-5-5", problemId: 3, requirements: 10, sourceChars: 32000 }),
    ).toBe(
      "/api/backend/classroom/classes/7/scoring-calculator?vendor=anthropic&method=agent&model=claude-haiku-5-5&problem_id=3&source_chars=32000&requirements=10",
    );
  });
});

describe("changeChoice", () => {
  it("프로바이더를 바꾸면 모델을 비운다", () => {
    expect(changeChoice({ vendor: "openai", model: "gpt-4.1-mini" }, "vendor", "anthropic")).toEqual({
      vendor: "anthropic",
      model: undefined,
    });
  });
  it("문제를 바꾸면 소스 크기·항목 수를 비운다", () => {
    expect(changeChoice({ problemId: 1, source: "p90", requirements: 9 }, "problemId", "2")).toEqual({
      problemId: 2,
      source: undefined,
      sourceChars: undefined,
      requirements: undefined,
    });
  });
  it("소스 크기를 고르면 입력한 글자 수를 비운다", () => {
    expect(changeChoice({ sourceChars: 99_000 }, "source", "p90")).toEqual({ source: "p90", sourceChars: undefined });
  });
  it("가정은 숫자로 옮기고 비우면 기본값으로 돌아간다", () => {
    expect(changeChoice({}, "requirements", "30")).toEqual({ requirements: 30 });
    expect(changeChoice({ requirements: 30 }, "requirements", undefined)).toEqual({ requirements: undefined });
  });
});

describe("parseAssumption", () => {
  it("쉼표를 지우고 숫자로 읽는다", () => {
    expect(parseAssumption("307,000")).toBe(307_000);
    expect(parseAssumption("0.58")).toBe(0.58);
  });
  it("비었거나 숫자가 아니면 기본값(undefined)", () => {
    expect(parseAssumption("")).toBeUndefined();
    expect(parseAssumption("abc")).toBeUndefined();
    expect(parseAssumption("-3")).toBeUndefined();
  });
});

describe("계산기 글자(#1308)", () => {
  it("한 번 호출 금액에 담는 크기가 같은 칸에서 나온다", () => {
    expect(submissionAmount(calcOf())).toMatch(/^약 [\d,]+원$/);
    expect(capacityText(calcOf())).toBe("300만 자 · 소스 파일 약 1,875개");
  });
  it("담지 못하면 클래스 설정대로 금액 옆에 낱말 하나(#1311)", () => {
    expect(submissionAmount(calcOf({ route: "over" }))).toBe("담지 못함 — 반려");
    expect(
      submissionAmount(calcOf({ route: "over", oversize: { policy: "agent", agent_model: "gpt-5-mini", agent_krw: 900 } })),
    ).toBe(`${formatKrw(900)} · 에이전트`);
    expect(
      submissionAmount(calcOf({ route: "over", oversize: { policy: "partial", agent_model: "", agent_krw: null } })),
    ).toBe(`${formatKrw(138)} · 일부만`);
  });
  it("에이전트는 에이전트 금액이다", () => {
    expect(submissionAmount(calcOf({ method: "agent" }))).toBe(formatKrw(400));
  });
  it("제출 한 건은 고른 모델 하나의 값이다", () => {
    expect(submissionAmount(calcOf({ staged: true }))).toBe(formatKrw(138));
  });
  it("금액 옆 줄은 그 금액이 기대는 소스 크기·항목 수다(#1492)", () => {
    const calc = { assumptions: { source_files: 20, source_chars: 32_000, requirements: 6 } } as unknown as ScoringCalculator;
    expect(submissionBasis(calc)).toBe("소스 20개 · 3.2만 자 · 항목 6개 기준");
  });
  it("글자 수는 만 단위로", () => {
    expect(charsLabel(32_000)).toBe("3.2만 자");
  });
  it("화면 코드에 표·한 학기·실측·토큰·시간 문구가 없다", () => {
    const root = join(__dirname, "..", "..");
    for (const file of ["lib/scoring/calculator.ts", "app/classes/[id]/scoring-calculator.tsx"]) {
      const source = readFileSync(join(root, file), "utf8");
      expect(source, file).not.toMatch(/표|학기|실측|토큰|가정한 시간|semester|regrade|근거 인용/);
    }
  });
});

function catalog(): ScoringCalculator {
  const m = (id: string, i: number, o: number) => ({ id, input_usd_per_million: i, output_usd_per_million: o, context_tokens: 1 });
  const row = (vendor: string, id: string, available: boolean) => ({ vendor, model_id: id, agent: { available } });
  return {
    providers: [
      { vendor: "openai", has_key: true, models: [m("gpt-5", 1.25, 10), m("gpt-4.1-mini", 0.4, 1.6), m("gpt-5-mini", 0.25, 2), m("gpt-5.1", 1.25, 8)] },
      { vendor: "anthropic", has_key: true, models: [m("claude-sonnet-5-5", 3, 15), m("claude-haiku-5-5", 0.1, 0.5)] },
      { vendor: "compat", has_key: true, models: [m("x", 1, 1)] },
    ],
    rows: [
      row("openai", "gpt-5", true),
      row("openai", "gpt-4.1-mini", false),
      row("openai", "gpt-5-mini", true),
      row("openai", "gpt-5.1", true),
      row("anthropic", "claude-sonnet-5-5", true),
      row("anthropic", "claude-haiku-5-5", true),
      row("compat", "x", false),
    ],
  } as unknown as ScoringCalculator;
}

describe("에이전트 가능 모델", () => {
  it("입력 단가가 가장 싼 모델을 고르고, 같으면 출력 단가로 가른다", () => {
    expect(cheapestAgentModel(catalog(), "openai")).toBe("gpt-5-mini");
    expect(cheapestAgentModel(catalog(), "anthropic")).toBe("claude-haiku-5-5");
  });
  it("불가 모델은 가능 목록에 없고, 가능 모델이 없으면 고르지 않는다", () => {
    expect([...agentModelIds(catalog(), "openai")].sort()).toEqual(["gpt-5", "gpt-5-mini", "gpt-5.1"]);
    expect(cheapestAgentModel(catalog(), "compat")).toBeUndefined();
  });
});

describe("모델 목록", () => {
  const withMethod = (vendor: string, method: string) => ({ ...catalog(), selection: { vendor, method } }) as unknown as ScoringCalculator;
  it("에이전트인 동안은 불가 모델이 없고, 한 번 호출이면 전부다", () => {
    expect(listedModels(withMethod("openai", "agent")).map((m) => m.id)).toEqual(["gpt-5", "gpt-5-mini", "gpt-5.1"]);
    expect(listedModels(withMethod("openai", "single")).map((m) => m.id)).toHaveLength(4);
    expect(listedModels(withMethod("anthropic", "agent")).map((m) => m.id)).toHaveLength(2);
  });
});
