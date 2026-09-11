// 이 앱의 next 검증(next-path.ts)은 frontend/lib/auth/next-path.ts의 isSafeNextPath와
// 같은 오픈 리다이렉트 방어 기법을 쓰는 **독립된 복사본**이다(#334 코드리뷰 지적) —
// 파일을 그대로 복사하지 않은 이유는 fallback 기본값("/"  vs "/console")과 placeholder
// 오리진 문자열이 앱마다 정당하게 다르기 때문이다(classroom/lib/design/tokens.test.ts가
// 쓰는 "한 글자도 다르지 않다" 방식은 여기선 못 쓴다).
//
// 대신 **판정 결과가 갈리지 않는지**를 본다. frontend/lib/auth/next-path.ts는 이미
// 한 번 실제로 뚫린 적이 있는 오픈 리다이렉트 검사다(그 파일 상단 주석 — backslash
// 정규화 우회) — 앞으로 그 파일에 새 우회 방어가 추가되는데 이 복사본이 따라가지
// 않으면, 같은 종류의 구멍이 이 앱에만 조용히 남는다. 이 테스트가 그 드리프트를
// 잡는다: 두 구현을 같은 입력 배터리에 돌려 boolean 판정이 같은지만 비교한다 —
// 텍스트가 아니라 동작의 동등성이다.
import * as path from "node:path";
import { pathToFileURL } from "node:url";

import { describe, expect, it } from "vitest";

import { isSafeNextPath as classroomIsSafeNextPath } from "./next-path";

const FRONTEND_NEXT_PATH = path.resolve(
  __dirname,
  "..",
  "..",
  "..",
  "frontend",
  "lib",
  "auth",
  "next-path.ts",
);

// next-path.test.ts(이 디렉터리)·frontend/lib/auth/next-path.test.ts가 각자 전수로
// 덮는 배터리에서 판정이 갈리는 대표 입력만 추린다 — 오픈 리다이렉트 검사의
// 핵심(호스트가 바뀌는가)을 건드리는 값들이다.
const CASES: Array<string | null | undefined> = [
  "/",
  "/console",
  "/classes/42",
  "/a/b/c?x=1#y",
  null,
  undefined,
  "",
  "https://evil.example.test/steal",
  "//evil.example.test",
  "/\\evil.example.test",
  "/\\/evil.example.test",
  "/a\\b",
  "/\t/evil.example.test",
  "/console\ttab-in-middle",
  "/\x00/evil.example.test",
  "/a b",
];

describe("isSafeNextPath 판정이 frontend/lib/auth/next-path.ts와 갈리지 않는다", () => {
  it("두 구현을 실제로 찾는다 — 경로가 바뀌면 이 검사가 조용히 빈손이 된다", async () => {
    const frontend = await import(pathToFileURL(FRONTEND_NEXT_PATH).href);
    expect(typeof frontend.isSafeNextPath).toBe("function");
  });

  it.each(CASES)("%j에 대한 판정이 같다", async (input) => {
    const frontend = await import(pathToFileURL(FRONTEND_NEXT_PATH).href);
    expect(
      classroomIsSafeNextPath(input),
      `입력 ${JSON.stringify(input)}에 대해 강의실과 공개 앱의 isSafeNextPath 판정이 갈렸다 — ` +
        "한쪽만 오픈 리다이렉트 방어를 고쳤을 가능성이 있다.",
    ).toBe(frontend.isSafeNextPath(input));
  });
});
