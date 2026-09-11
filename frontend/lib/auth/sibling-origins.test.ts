// 형제 오리진 허용목록 (#297 후속).
//
// 이 검사가 하는 일은 「돌아갈 곳이 **우리 것인가**」 하나다. 오픈 리다이렉트를
// 막는 기존 검사(lib/auth/next-path.ts)를 대체하지 않는다 — 그것은 경로를 보고,
// 이것은 오리진을 본다. 둘 다 통과해야 다른 서브도메인으로 돌아간다.
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { configuredSiblingOrigins, resolveSiblingOrigin } from "./sibling-origins";

const ORIGINAL = { ...process.env };
const CLASSROOM = "https://classroom.laurio.example";

beforeEach(() => {
  process.env = { ...ORIGINAL, LAURIO_CLASSROOM_ORIGIN: CLASSROOM };
});
afterEach(() => {
  process.env = { ...ORIGINAL };
});

describe("설정된 우리 오리진만 통과한다", () => {
  it("정확히 같은 오리진", () => {
    expect(resolveSiblingOrigin(CLASSROOM)).toBe(CLASSROOM);
  });

  it("끝의 슬래시는 같은 것으로 본다", () => {
    expect(resolveSiblingOrigin(`${CLASSROOM}/`)).toBe(CLASSROOM);
  });

  it("경로가 붙어 와도 오리진만 남긴다 — 경로는 next 가 따로 검증한다", () => {
    expect(resolveSiblingOrigin(`${CLASSROOM}/classes/1`)).toBe(CLASSROOM);
  });
});

describe("우리 것이 아니면 거절한다", () => {
  it.each([
    ["접미어 트릭", "https://classroom.laurio.example.evil.test"],
    ["authority 트릭", "https://classroom.laurio.example@evil.test"],
    ["접두어만 같은 것", "https://classroom.laurio.exampleX"],
    ["다른 스킴", "ftp://classroom.laurio.example"],
    ["스킴 없는 것", "classroom.laurio.example"],
    ["상대 경로", "/classes/1"],
    ["프로토콜 상대", "//evil.test"],
    ["빈 문자열", ""],
    ["자바스크립트 스킴", "javascript:alert(1)"],
  ])("%s", (_label, candidate) => {
    expect(resolveSiblingOrigin(candidate)).toBeNull();
  });

  it("null·undefined", () => {
    expect(resolveSiblingOrigin(null)).toBeNull();
    expect(resolveSiblingOrigin(undefined)).toBeNull();
  });
});

describe("설정이 없으면 복귀 자체가 꺼진다 — 안전한 쪽으로 실패한다", () => {
  it("환경변수가 비면 목록이 비고 무엇도 통과하지 못한다", () => {
    delete process.env.LAURIO_CLASSROOM_ORIGIN;
    expect(configuredSiblingOrigins()).toEqual([]);
    expect(resolveSiblingOrigin(CLASSROOM)).toBeNull();
  });

  it("값이 URL 로 파싱되지 않으면 그 항목은 목록에 안 든다", () => {
    process.env.LAURIO_CLASSROOM_ORIGIN = "not a url";
    expect(configuredSiblingOrigins()).toEqual([]);
  });
});
