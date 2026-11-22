import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { calculatorPath, capacityText, changeChoice, charsLabel, parseAssumption, submissionAmount, type ScoringCalculator } from "./calculator";
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
};
const NONE = { sample_count: 0, median: null, p90: null };

function calcOf(
  overrides: { method?: string; route?: string; staged?: boolean; escalationKrw?: number | null; agentKrw?: number | null } = {},
): ScoringCalculator {
  const { method = "single", route = "single", staged = false, escalationKrw = null, agentKrw = 400 } = overrides;
  // 금액·크기 글자에 쓰는 칸만 채운 흉내
  return {
    selection: { model_id: "m", method },
    staged: { enabled: staged },
    escalation: { model_id: escalationKrw === null ? null : "big", per_submission_krw: escalationKrw ?? 0 },
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
  it("담지 못하면 금액 자리에 보류", () => {
    expect(submissionAmount(calcOf({ route: "hold" }))).toBe("담지 못함 — 보류");
  });
  it("에이전트는 에이전트 금액이다", () => {
    expect(submissionAmount(calcOf({ method: "agent" }))).toBe(formatKrw(400));
  });
  it("새 채점기와 재판정 모델이 함께 있을 때만 금액에 재판정 몫이 합쳐진다", () => {
    const plain = submissionAmount(calcOf({ staged: true }));
    expect(submissionAmount(calcOf({ staged: false, escalationKrw: 5000 }))).toBe(plain);
    expect(submissionAmount(calcOf({ staged: true, escalationKrw: 5000 }))).toBe(formatKrw(138 + 5000));
    expect(submissionAmount(calcOf({ staged: true, escalationKrw: 5000 }))).not.toBe(plain);
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
