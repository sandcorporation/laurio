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

describe("개인정보처리방침 서비스 오류 기록(#928)", () => {
  it("1항에 항목과 공통 문서 링크, 2항에 목적, 3항에 90일 자동 삭제를 적는다", () => {
    expect(page).toContain('data-testid="privacy-error-log-item"');
    expect(page).toContain("서비스 이용 중: 오류 기록");
    expect(page).toContain("로그인한 경우 회원 식별 번호");
    expect(page).toContain("https://sandcorporation.github.io/privacy-and-terms/errors/");
    expect(page).toContain("서비스 오류의 발견·수정과 안정성 확보");
    expect(page).toMatch(/오류 기록은 수집한 날부터 90일이 지나면 자동으로 삭제합니다/);
  });

  it("호스트·내부 주소는 적지 않고, 위탁·국외 이전 절에는 넣지 않는다", () => {
    expect(page).not.toMatch(/glitchtip/i);
    // 적힌 주소는 공개 문서 사이트뿐이다 — 내부 호스트(오류 수집기 등)가 끼면 여기서 걸린다.
    const hosts = new Set([...page.matchAll(/https?:\/\/([A-Za-z0-9.-]+)/g)].map((m) => m[1]));
    expect([...hosts]).toEqual(["sandcorporation.github.io"]);
    const outsourcing = page.slice(page.indexOf('title="5. 개인정보 처리의 위탁"'), page.indexOf('title="7. '));
    expect(outsourcing).not.toContain("오류 기록");
  });
});
