// 다시 불러오기가 화면을 비우면 안 된다.
//
// **실제로 사람이 겪었다.** 참여자가 소스 파일을 제출하면 문제 화면 전체가
// 「불러오는 중...」으로 바뀌었다가 다시 그려졌고, 그 사이 고른 제출 형식이
// 초기화됐다. 원인은 훅의 `reload()` 가 매번 상태를 `loading` 으로 되돌리는
// 것이었다 — 페이지는 `loading` 이면 본문 대신 「불러오는 중」만 그리므로 본문이
// 통째로 언마운트됐다가 다시 마운트된다. 예전에도 제출 직후 한 번은 그랬지만
// SSE(ADR-0046)가 재조회 계기를 늘리면서(제출 신호·채점 신호·재연결·끊긴 동안의
// 폴링) 한 번 제출에 여러 번, 채점이 끝나는 몇 분 뒤에도 깜빡이게 됐다.
//
// 그래서 규칙은 이렇다: **밖으로 `reload` 를 내주는 훅은 그 함수 안에서
// `status: "loading"` 으로 되돌리지 않는다.** `loading` 은 처음 불러올 때와
// 보고 있는 대상(클래스·문제 id)이 바뀔 때만 — 즉 식별자에 걸린 effect 에서만 —
// 쓴다. 이미 그린 데이터는 새 응답이 올 때까지 그대로 둔다.
//
// 컴포넌트 테스트를 두지 않는 앱이라(ADR-0017/0021) 이 규칙은 소스를 읽어
// 구조로 지킨다(`runtime-config.test.ts` 와 같은 방식).
import * as fs from "node:fs";
import * as path from "node:path";

import { describe, expect, it } from "vitest";

const LIB_ROOT = path.resolve(__dirname, "..");

function walk(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) return walk(full);
    return /^use-.*\.tsx?$/.test(e.name) && !e.name.includes(".test.") ? [full] : [];
  });
}

/** `from` 위치의 첫 `{` 부터 짝이 맞는 `}` 까지. */
function blockFrom(source: string, from: number): string {
  const start = source.indexOf("{", from);
  if (start < 0) return "";
  let depth = 0;
  for (let i = start; i < source.length; i++) {
    if (source[i] === "{") depth++;
    else if (source[i] === "}" && --depth === 0) return source.slice(start, i + 1);
  }
  return source.slice(start);
}

/** 훅이 밖으로 내주는 재조회 함수의 이름 — `reload` 또는 `reload: <이름>`. */
function exportedReloadName(source: string): string | null {
  const aliased = source.match(/return\s*\{[^}]*\breload\s*:\s*(\w+)/);
  if (aliased) return aliased[1];
  return /return\s*\{[^}]*\breload\b/.test(source) ? "reload" : null;
}

function reloadBody(source: string, name: string): string {
  const decl = new RegExp(`(?:const\\s+${name}\\s*=|function\\s+${name}\\s*\\()`).exec(source);
  return decl ? blockFrom(source, decl.index) : "";
}

const HOOKS = walk(LIB_ROOT)
  .map((file) => ({ file, source: fs.readFileSync(file, "utf8") }))
  .map(({ file, source }) => ({ file, source, name: exportedReloadName(source) }))
  .filter((h): h is { file: string; source: string; name: string } => h.name !== null);

describe("다시 불러오기는 이미 그린 화면을 비우지 않는다", () => {
  it("검사 대상 훅을 실제로 찾는다", () => {
    expect(HOOKS.map((h) => path.basename(h.file))).toContain("use-my-problem.ts");
  });

  it.each(HOOKS.map((h) => [path.relative(LIB_ROOT, h.file), h] as const))(
    "%s 의 reload 는 loading 으로 되돌리지 않는다",
    (_rel, hook) => {
      const body = reloadBody(hook.source, hook.name);
      expect(body, "reload 함수 본문을 찾지 못했다").not.toBe("");
      expect(body).not.toMatch(/status:\s*"loading"/);
    },
  );
});
