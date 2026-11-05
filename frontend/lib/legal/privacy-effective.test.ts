import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { effectiveNotice } from "./effective-notice";

// 방침 화면(#897)은 서버 컴포넌트라 이 러너(순수 모듈)가 그리지 못한다 — 화면이 쓰는 상수를 소스에서 읽어
// 같은 함수로 시행일 전·후 문구를 견준다.
const page = readFileSync(new URL("../../app/privacy/page.tsx", import.meta.url), "utf-8");
const iso = (name: string) => new RegExp(`const ${name} = "(\\d{4}-\\d{2}-\\d{2})";`).exec(page)?.[1] ?? "";

describe("개인정보처리방침 시행일 표시", () => {
  const effective = iso("EFFECTIVE_ISO");

  it("현재 판 시행일은 병합일(2026-11-05)+7일이다", () => {
    expect(effective).toBe("2026-11-12");
  });

  it("시행일 전에는 개정 예정, 시행일 0시(KST)부터는 시행일만", () => {
    expect(effectiveNotice(effective, new Date("2026-11-11T14:59:00Z"))).toBe("개정 예정 · 시행일 2026년 11월 12일");
    expect(effectiveNotice(effective, new Date("2026-11-11T15:00:00Z"))).toBe("시행일 2026년 11월 12일");
  });

  it("Anthropic 이전 개정의 시행일(키 잠금 기준)은 따로 2026-11-06 이다", () => {
    expect(iso("ANTHROPIC_TRANSFER_EFFECTIVE_ISO")).toBe("2026-11-06");
  });

  it("6항 두 줄(OpenAI·Anthropic)이 완성도 채점을 이전 목적에 적는다", () => {
    const lines = page.match(/이전 목적: 요구사항 충족 여부의 자동 채점, 완성도 채점과 그 근거 생성/g) ?? [];
    expect(lines).toHaveLength(2);
  });
});
