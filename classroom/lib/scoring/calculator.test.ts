import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  agentLimitsLine,
  agentNote,
  calculatorPath,
  capacityLabel,
  changeChoice,
  escalationCost,
  fromLabel,
  parseAssumption,
  singleNote,
  sourceLabel,
  twoStepLine,
} from "./calculator";

const STAGED = { enabled: true, threshold_chars: 120_000, budget_chars: 60_000 };
const SINGLE = {
  input_tokens: 1,
  output_tokens: 1,
  usd: 0.1,
  krw: 138,
  open_ended: false,
  fits: true,
  capacity_chars: 232_000,
  capacity_chars_hangul: 166_000,
  route: "single",
  seconds: 5,
};

describe("calculatorPath", () => {
  it("빈 칸은 싣지 않는다", () => {
    expect(calculatorPath(7, {})).toBe("/api/backend/classroom/classes/7/scoring-calculator");
  });
  it("고른 칸과 바꿔 본 가정을 쿼리로 싣는다", () => {
    expect(
      calculatorPath(7, { vendor: "anthropic", method: "agent", model: "claude-haiku-5-5", problemId: 3, source: "p90", students: 10, regradeRate: 0 }),
    ).toBe(
      "/api/backend/classroom/classes/7/scoring-calculator?vendor=anthropic&method=agent&model=claude-haiku-5-5&problem_id=3&source=p90&students=10&regrade_rate=0",
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
    expect(changeChoice({}, "students", "30")).toEqual({ students: 30 });
    expect(changeChoice({ students: 30 }, "students", undefined)).toEqual({ students: undefined });
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

describe("라벨", () => {
  it("가정의 출처", () => {
    expect([fromLabel("assumed"), fromLabel("problem"), fromLabel("custom")]).toEqual(["가정", "문제", "입력"]);
  });
  it("소스 크기는 출처와 글자 수", () => {
    expect(sourceLabel({ key: "median", chars: 32_000, measured: false })).toBe("가정 중앙 · 3.2만 자");
    expect(sourceLabel({ key: "p90", chars: 6_120, measured: true })).toBe("제출 큰 쪽(p90) · 6,120 자");
  });
  it("감당 크기는 글자 수 숫자다 — 「모델 한도까지」 같은 말이 아니다", () => {
    expect(capacityLabel(232_000)).toBe("23.2만 자");
    expect(singleNote(SINGLE, STAGED)).toBe("감당 23.2만 자 · 한글 위주 16.6만 자");
    expect(singleNote(SINGLE, STAGED)).not.toContain("모델 한도까지");
  });
  it("감당 크기를 넘으면 보류, staged 두 걸음이면 읽는 상한", () => {
    expect(singleNote({ ...SINGLE, route: "hold", fits: false, krw: 0 }, STAGED)).toBe(
      "담지 못함 — 보류(채점 안 함) · 감당 23.2만 자 · 한글 위주 16.6만 자",
    );
    expect(singleNote({ ...SINGLE, route: "two_step" }, STAGED)).toBe("두 걸음 · 고른 파일 6만 자까지 읽음");
  });
  it("두 걸음·에이전트 상한은 코드의 숫자 그대로", () => {
    expect(twoStepLine(STAGED)).toBe("12만 자 넘으면 두 걸음 — 고른 파일 6만 자까지 읽음");
    expect(
      agentLimitsLine({
        max_zip_bytes: 100 * 1024 * 1024,
        max_extracted_bytes: 256 * 1024 * 1024,
        max_zip_entries: 50_000,
        attempt_seconds: 300,
        attempts: 2,
        budget_usd: 1,
      }),
    ).toBe("zip 100MB · 풀린 크기 256MB · 파일 5만 개 · 시간 300초 × 2회 · 한 건 $1");
  });
  it("에이전트는 가정한 시간을 쓰고, 실측이 있으면 중앙을 옆에 붙인다", () => {
    const none = { sample_count: 2, median: null, p90: null };
    expect(agentNote({ available: true, usd: 0.1, krw: 138, seconds: 12.5, measured_krw: none, measured_seconds: none })).toBe("12.5초 가정");
    expect(
      agentNote({
        available: true,
        usd: 0.1,
        krw: 138,
        seconds: 12.5,
        measured_krw: { sample_count: 4, median: 45, p90: 120 },
        measured_seconds: { sample_count: 4, median: 40, p90: 150 },
      }),
    ).toBe("실측 중앙 약 45원 · 40초 (4건)");
  });
  it("가정·실측 없음 글자가 라벨에 없다", () => {
    expect(agentNote({ available: true, usd: 0.1, krw: 1, seconds: 1, measured_krw: { sample_count: 0, median: null, p90: null }, measured_seconds: { sample_count: 0, median: null, p90: null } })).not.toContain("실측 없음");
  });
});

describe("escalationCost", () => {
  it("꺼졌으면 줄이 없다", () => {
    expect(escalationCost({ model_id: null, per_suspect: null, suspect_rate: 0.025, per_submission_krw: 0 })).toBeNull();
  });
  it("고른 모델의 의심 한 건당 값과 가정한 비율, 제출 한 건에 더해지는 값", () => {
    expect(
      escalationCost({
        model_id: "gpt-4.1",
        per_suspect: { input_tokens: 1, output_tokens: 1, usd: 0.1, krw: 140, open_ended: false },
        suspect_rate: 0.025,
        per_submission_krw: 21,
      }),
    ).toEqual({
      model: "gpt-4.1",
      perSuspect: expect.stringMatching(/^의심 한 건당 /),
      rate: "2.5%",
      perSubmission: expect.stringMatching(/^제출 한 건에 /),
    });
  });
});

describe("두루뭉술한 말", () => {
  it("화면 코드 어디에도 「모델 한도까지」·「실측 없음」이 없다", () => {
    const root = join(__dirname, "..", "..");
    for (const file of ["lib/scoring/calculator.ts", "app/classes/[id]/scoring-calculator.tsx"]) {
      const source = readFileSync(join(root, file), "utf8");
      expect(source, file).not.toContain("모델 한도까지");
      expect(source, file).not.toContain("실측 없음");
    }
  });
});
