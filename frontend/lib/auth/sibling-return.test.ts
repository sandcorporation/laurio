// 강의실에서 건너온 사람이 돌아갈 주소(#1478 5) — `from_origin` 은 허용목록과 완전 일치일 때만, `from_path` 는
// **그 오리진 안의 같은 출처 경로**일 때만 붙는다. 열린 리다이렉트(다른 호스트·`//`·`javascript:`)는 오리진 첫 화면으로 떨어진다.
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { resolveSiblingReturnUrl } from "./sibling-origins";

const ORIGINAL = { ...process.env };
const CLASSROOM = "https://classroom.codemit.example";

beforeEach(() => {
  process.env = { ...ORIGINAL, CODEMIT_CLASSROOM_ORIGIN: CLASSROOM };
});
afterEach(() => {
  process.env = { ...ORIGINAL };
});

describe("resolveSiblingReturnUrl", () => {
  it("오리진과 같은 출처 경로·쿼리를 이어 돌려준다", () => {
    expect(resolveSiblingReturnUrl(CLASSROOM, "/classes/7?tab=participants")).toBe(
      `${CLASSROOM}/classes/7?tab=participants`,
    );
  });

  it("경로가 없으면 오리진만 돌려준다", () => {
    expect(resolveSiblingReturnUrl(CLASSROOM, undefined)).toBe(CLASSROOM);
    expect(resolveSiblingReturnUrl(CLASSROOM, "")).toBe(CLASSROOM);
  });

  it("허용 오리진이 아니면 경로가 아무리 멀쩡해도 null", () => {
    expect(resolveSiblingReturnUrl("https://evil.example", "/classes/7")).toBeNull();
    expect(resolveSiblingReturnUrl(null, "/classes/7")).toBeNull();
  });

  it("경로의 @ 는 호스트가 아니라 경로로 남는다", () => {
    expect(resolveSiblingReturnUrl(CLASSROOM, "/@evil.example")).toBe(`${CLASSROOM}/@evil.example`);
  });

  it.each([
    ["다른 호스트(스킴 상대)", "//evil.example/x"],
    ["다른 호스트(절대)", "https://evil.example/x"],
    ["javascript 스킴", "javascript:alert(1)"],
    ["역슬래시 우회", "/\\evil.example"],
    ["역슬래시 앞 슬래시", "\\/evil.example"],
    ["탭 우회", "/\t/evil.example"],
    ["개행 우회", "/\n/evil.example"],
    ["제어 문자", "/classes/\u0000"],
    ["슬래시로 시작하지 않음", "classes/7"],
  ])("%s 는 오리진 첫 화면으로 떨어진다", (_name, path) => {
    expect(resolveSiblingReturnUrl(CLASSROOM, path)).toBe(CLASSROOM);
  });
});
