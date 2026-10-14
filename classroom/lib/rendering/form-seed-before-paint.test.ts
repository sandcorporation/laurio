// 서버에서 읽은 값을 폼 칸에 넣는 일은 그리기 **전에** 끝나야 한다(#675).
//
// **실제로 열차가 붉었다**(codemit-train #1810). 문제 편집 화면이 칸을 `useState("")` 로 시작하고
// 서버 제목을 `useEffect(() => { if (state.status === "ready") setTitle(state.problem.title) }, [state])`
// 로 넣었다. 효과는 그리기 뒤 따로 돌므로, 빈 칸이 그려진 그 틈에 e2e 의 `fill` 이 새 제목을 넣고 →
// 효과가 서버 제목으로 덮고 → 이미 풀린 「저장」이 옛 제목을 저장했다. 사람은 그 틈에 칠 수 없지만
// 자동화는 그리는 순간 친다(붙여넣기·자동 채움도 같다).
//
// 그래서 규칙은 이렇다: **효과(`useEffect`·`useLayoutEffect`) 안에서 훅이 돌려준 읽은 상태
// (`state`·`preview`·`problemState`·… — 이름은 가리지 않는다, #687)의 필드로 `setX` 를 바로 부르지
// 않는다.** 함수형 갱신(`setX((current) => current === "" ? preview.… : current)`)은 된다 — 먼저 친
// 값을 덮지 않으니 같은 흔들림이 나지 않는다(가입·초대 화면의 이름 칸이 이 모양이다).
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
  const re = /use(?:Layout)?Effect\(\s*(?:\(\)\s*=>|function\s*\w*\s*\(\))\s*\{/g;
  for (let m = re.exec(source); m; m = re.exec(source)) bodies.push(blockFrom(source, m.index));
  return bodies;
}

const SCREENS = walk(APP_ROOT).map((file) => ({ file, source: fs.readFileSync(file, "utf8") }));

// React 가 준 훅은 읽은 상태가 아니다 — 나머지 `const x = useY(…)` 의 x 를 읽은 상태로 본다.
const REACT_HOOKS = new Set(["useRef", "useState", "useCallback", "useMemo", "useReducer", "useId"]);

/** 이 소스에서 훅이 돌려준 변수 이름들(`state` 는 늘 든다). */
function hookResultNames(source: string): string[] {
  const names = new Set(["state"]);
  for (const m of source.matchAll(/\bconst\s+(\w+)\s*=\s*(use[A-Z]\w*)\(/g)) {
    if (!REACT_HOOKS.has(m[2])) names.add(m[1]);
  }
  return [...names];
}

/** 읽은 상태의 필드로 칸을 채우는 setter 호출 — `setTitle(state.problem.title)` 같은 모양.
 * 첫 인자가 `(` 로 시작하는 함수형 갱신은 걸리지 않는다. */
function seedsFromState(names: string[]): RegExp {
  return new RegExp(`\\bset[A-Z]\\w*\\(\\s*(?:${names.join("|")})\\??\\.`);
}

describe("읽은 값으로 폼 칸을 채우는 일은 효과가 아니라 렌더 중에 한다", () => {
  it("이 규칙이 지키는 화면을 실제로 찾는다", () => {
    const rel = SCREENS.map((s) => path.relative(APP_ROOT, s.file));
    expect(rel).toContain(path.join("classes", "[id]", "problems", "[problemId]", "page.tsx"));
  });

  it.each(SCREENS.map((s) => [path.relative(APP_ROOT, s.file), s] as const))(
    "%s 의 효과는 읽은 상태로 칸을 채우지 않는다",
    (_rel, screen) => {
      const seeds = seedsFromState(hookResultNames(screen.source));
      for (const body of effectBodies(screen.source)) expect(body).not.toMatch(seeds);
    },
  );

  it("이름이 state 가 아니어도, useLayoutEffect 여도 잡고 함수형 갱신은 통과시킨다", () => {
    const join = SCREENS.find((s) => s.file.endsWith(path.join("join", "[code]", "page.tsx")))!;
    const seeds = seedsFromState(hookResultNames(join.source));
    const functional = 'setDisplayName((current) => (current === "" ? preview.preview.suggested_name! : current));';
    expect(join.source).toContain(functional);
    expect(functional).not.toMatch(seeds);
    // 반례 — 효과가 먼저 친 이름을 덮는 모양이면 붉어진다.
    const direct = join.source.replace(functional, "setDisplayName(preview.preview.suggested_name);");
    expect(effectBodies(direct).some((body) => seeds.test(body))).toBe(true);
    const layout = "useLayoutEffect(function seed() { setTitle(problemState.problem.title); }, [problemState]);";
    expect(effectBodies(layout).some((body) => seedsFromState(["problemState"]).test(body))).toBe(true);
  });

  it("문제 편집 화면은 문제를 읽은 그 렌더에서 칸을 맞춘다", () => {
    const page = SCREENS.find((s) => s.file.endsWith(path.join("[problemId]", "page.tsx")))!;
    expect(page.source).toMatch(/state\.problem\s*!==\s*\w+/);
  });
});
