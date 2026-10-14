// 서버에서 읽은 값을 폼 칸에 넣는 일은 그리기 **전에** 끝나야 한다(#675).
//
// **실제로 열차가 붉었다**(codemit-train #1810). 문제 편집 화면이 칸을 `useState("")` 로 시작하고
// 서버 제목을 `useEffect(() => { if (state.status === "ready") setTitle(state.problem.title) }, [state])`
// 로 넣었다. 효과는 그리기 뒤 따로 돌므로, 빈 칸이 그려진 그 틈에 e2e 의 `fill` 이 새 제목을 넣고 →
// 효과가 서버 제목으로 덮고 → 이미 풀린 「저장」이 옛 제목을 저장했다. 사람은 그 틈에 칠 수 없지만
// 자동화는 그리는 순간 친다(붙여넣기·자동 채움도 같다).
//
// 그래서 규칙은 이렇다: **`useEffect` 안에서 읽은 상태(`state.…`)로 `setX` 를 부르지 않는다.**
// 읽은 값으로 칸을 채우는 것은 렌더 중 「읽은 객체가 바뀌었으면 맞춘다」로 한다 — React 는 렌더 중의
// setState 를 커밋 전에 다시 렌더해 반영하므로 첫 그리기부터 칸에 서버 값이 있다. `reload()` 뒤 새
// 객체가 오면 같은 자리에서 다시 맞춘다.
//
// 컴포넌트 테스트를 두지 않는 앱이라(ADR-0017/0021, 순수 함수 시임은 react 를 못 본다) 이 규칙은
// 소스를 읽어 구조로 지킨다(`refetch-keeps-screen.test.ts` 와 같은 방식).
import * as fs from "node:fs";
import * as path from "node:path";

import { describe, expect, it } from "vitest";

const APP_ROOT = path.resolve(__dirname, "../../app");

function walk(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) return walk(full);
    return e.name.endsWith(".tsx") ? [full] : [];
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

function effectBodies(source: string): string[] {
  const bodies: string[] = [];
  const re = /useEffect\(\s*\(\)\s*=>\s*\{/g;
  for (let m = re.exec(source); m; m = re.exec(source)) bodies.push(blockFrom(source, m.index));
  return bodies;
}

const SCREENS = walk(APP_ROOT).map((file) => ({ file, source: fs.readFileSync(file, "utf8") }));

// 읽은 상태로 칸을 채우는 setter 호출 — `setTitle(state.problem.title)` 같은 모양.
const SEEDS_FROM_STATE = /\bset[A-Z]\w*\(\s*state\./;

describe("읽은 값으로 폼 칸을 채우는 일은 효과가 아니라 렌더 중에 한다", () => {
  it("이 규칙이 지키는 화면을 실제로 찾는다", () => {
    const rel = SCREENS.map((s) => path.relative(APP_ROOT, s.file));
    expect(rel).toContain(path.join("classes", "[id]", "problems", "[problemId]", "page.tsx"));
  });

  it.each(SCREENS.map((s) => [path.relative(APP_ROOT, s.file), s] as const))(
    "%s 의 useEffect 는 읽은 상태로 칸을 채우지 않는다",
    (_rel, screen) => {
      for (const body of effectBodies(screen.source)) expect(body).not.toMatch(SEEDS_FROM_STATE);
    },
  );

  it("문제 편집 화면은 문제를 읽은 그 렌더에서 칸을 맞춘다", () => {
    const page = SCREENS.find((s) => s.file.endsWith(path.join("[problemId]", "page.tsx")))!;
    expect(page.source).toMatch(/state\.problem\s*!==\s*\w+/);
  });
});
