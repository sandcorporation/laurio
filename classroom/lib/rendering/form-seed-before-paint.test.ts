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
// **잡지 못하는 모양**(정규식의 한계): 읽은 값을 지역 변수로 한 번 거쳐 넣는 것
// (`const target = pick(state.rows); setX(target.id)` — 템플릿 공유 화면의 복사 대상이 이 모양이었다, #691),
// 훅 결과를 다른 이름에 다시 담는 것, 효과 밖의 함수가 대신 부르는 것. 이런 모양은 리뷰가 본다.
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

/** `open` 위치의 `(` 와 짝이 맞는 `)` 사이의 글. 괄호 셋을 함께 센다. */
function parenInner(source: string, open: number): string {
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    const c = source[i];
    if (c === "(" || c === "[" || c === "{") depth++;
    else if ((c === ")" || c === "]" || c === "}") && --depth === 0) return source.slice(open + 1, i);
  }
  return source.slice(open + 1);
}

/** 호출 인자 글에서 첫 인자(최상위 `,` 앞까지). */
function firstArg(inner: string): string {
  let depth = 0;
  for (let i = 0; i < inner.length; i++) {
    const c = inner[i];
    if (c === "(" || c === "[" || c === "{") depth++;
    else if (c === ")" || c === "]" || c === "}") depth--;
    else if (c === "," && depth === 0) return inner.slice(0, i);
  }
  return inner;
}

/** 효과에 넘긴 함수 전부 — `() => { … }`·`function f() { … }`·본문이 표현식인 `() => setX(…)`(#691). */
function effectBodies(source: string): string[] {
  const bodies: string[] = [];
  for (const m of source.matchAll(/use(?:Layout)?Effect\(/g)) {
    bodies.push(firstArg(parenInner(source, m.index + m[0].length - 1)));
  }
  return bodies;
}

const SCREENS = walk(APP_ROOT).map((file) => ({ file, source: fs.readFileSync(file, "utf8") }));

// React 가 준 훅은 읽은 상태가 아니다 — 나머지 훅이 돌려준 이름을 읽은 상태로 본다.
const REACT_HOOKS = new Set(["useRef", "useState", "useCallback", "useMemo", "useReducer", "useId"]);

/** 구조 분해 안의 이름들 — `{ state: classState, reload }` 는 classState·reload, `[a, b]` 는 a·b. */
function boundNames(pattern: string): string[] {
  return pattern
    .split(",")
    .map((part) => part.replace(/^\s*\.\.\./, "").replace(/=[\s\S]*$/, ""))
    .map((part) => (part.includes(":") ? part.slice(part.indexOf(":") + 1) : part).trim())
    .filter((name) => /^\w+$/.test(name));
}

/** 이 소스에서 훅이 돌려준 변수 이름들(`state` 는 늘 든다). `const x =`·`const { a: x } =`·`const [x] =`
 * 셋을 모은다(#691). `useBackendQuery<T>(` 처럼 타입 인자가 끼어도 모은다(#695). */
function hookResultNames(source: string): string[] {
  const names = new Set(["state"]);
  const re = /\bconst\s+(?:(\w+)|\{([^}]*)\}|\[([^\]]*)\])\s*=\s*(use[A-Z]\w*)(?:<[^>]*>)?\(/g;
  for (const m of source.matchAll(re)) {
    if (REACT_HOOKS.has(m[4])) continue;
    for (const name of m[1] ? [m[1]] : boundNames(m[2] ?? m[3])) names.add(name);
  }
  return [...names];
}

// 이름이 set 으로 시작해도 setter 가 아니다 — 콜백이 매개변수 없이 상태를 읽으면 함수형 갱신으로 잘못 읽힌다(#695).
const TIMERS = new Set(["setTimeout", "setInterval", "setImmediate"]);

/** 이 효과 본문이 읽은 상태의 필드로 칸을 채우는가 — `setTitle(state.problem.title)` 같은 모양.
 * 함수형 갱신은 자기 매개변수(먼저 친 값)를 본문에서 다시 쓸 때만 통과한다 — `setX((c) => c === "" ? … : c)`
 * 는 먼저 친 값을 덮지 않지만, `setX(() => state.…)`·`setX((c) => state.…)` 는 옛 버그와 똑같이 덮는다(#691). */
function seedsFromState(body: string, names: string[]): boolean {
  const read = new RegExp(`\\b(?:${names.join("|")})\\??\\.`);
  for (const m of body.matchAll(/\bset[A-Z]\w*\(/g)) {
    if (TIMERS.has(m[0].slice(0, -1))) continue;
    const arg = firstArg(parenInner(body, m.index + m[0].length - 1));
    const updater = /^\s*(?:\(\s*(\w*)\s*(?::[^)]*)?\)|(\w+))\s*=>([\s\S]*)$/.exec(arg);
    if (!updater) {
      if (new RegExp(`^\\s*${read.source}`).test(arg)) return true;
      continue;
    }
    const param = updater[1] || updater[2];
    const reusesParam = param !== undefined && param !== "" && new RegExp(`\\b${param}\\b`).test(updater[3]);
    if (read.test(updater[3]) && !reusesParam) return true;
  }
  return false;
}

describe("읽은 값으로 폼 칸을 채우는 일은 효과가 아니라 렌더 중에 한다", () => {
  it("이 규칙이 지키는 화면을 실제로 찾는다", () => {
    const rel = SCREENS.map((s) => path.relative(APP_ROOT, s.file));
    expect(rel).toContain(path.join("classes", "[id]", "problems", "[problemId]", "page.tsx"));
  });

  it.each(SCREENS.map((s) => [path.relative(APP_ROOT, s.file), s] as const))(
    "%s 의 효과는 읽은 상태로 칸을 채우지 않는다",
    (_rel, screen) => {
      const names = hookResultNames(screen.source);
      for (const body of effectBodies(screen.source)) expect(seedsFromState(body, names), body).toBe(false);
    },
  );

  it("이름이 state 가 아니어도, useLayoutEffect 여도 잡고 함수형 갱신은 통과시킨다", () => {
    const join = SCREENS.find((s) => s.file.endsWith(path.join("join", "[code]", "page.tsx")))!;
    const names = hookResultNames(join.source);
    const functional = 'setDisplayName((current) => (current === "" ? preview.preview.suggested_name! : current));';
    expect(join.source).toContain(functional);
    expect(seedsFromState(functional, names)).toBe(false);
    // 반례 — 효과가 먼저 친 이름을 덮는 모양이면 붉어진다.
    const direct = join.source.replace(functional, "setDisplayName(preview.preview.suggested_name);");
    expect(effectBodies(direct).some((body) => seedsFromState(body, names))).toBe(true);
    const layout = "useLayoutEffect(function seed() { setTitle(problemState.problem.title); }, [problemState]);";
    expect(effectBodies(layout).some((body) => seedsFromState(body, ["problemState"]))).toBe(true);
  });

  it("훅이 돌려준 이름은 그냥 받든, 별칭 구조 분해로 받든, 배열 분해로 받든 모은다(#691)", () => {
    const edit = SCREENS.find((s) => s.file.endsWith(path.join("[problemId]", "page.tsx")))!;
    expect(edit.source).toContain("const { state: modelsState } = useScoringModels(");
    expect(hookResultNames(edit.source)).toEqual(expect.arrayContaining(["classState", "modelsState", "costState"]));
    // 반례 — 실제 화면에 별칭으로 받은 상태를 효과로 칸에 넣는 줄을 끼우면 붉어진다.
    const seeded = edit.source.replace(
      "const { state: modelsState } = useScoringModels(classId);",
      "const { state: modelsState } = useScoringModels(classId);\n  useEffect(() => { setModel(modelsState.models[0]); }, [modelsState]);",
    );
    expect(effectBodies(seeded).some((body) => seedsFromState(body, hookResultNames(seeded)))).toBe(true);
    // 반례 셋 — 받는 모양마다.
    const effect = "useEffect(() => { setTitle(x.problem.title); }, [x]);";
    for (const binding of ["const x = useProblem(id);", "const { a: x } = useProblem(id);", "const [x] = useProblem(id);"]) {
      const source = `${binding}\n${effect}`;
      expect(effectBodies(source).some((body) => seedsFromState(body, hookResultNames(source))), binding).toBe(true);
    }
    // 타입 인자가 낀 훅 호출도 모은다 — 강사 구역의 두 목록 상태(#695).
    const instructors = SCREENS.find((s) => s.file.endsWith(path.join("[id]", "instructors-section.tsx")))!;
    expect(instructors.source).toContain("useBackendQuery<ClassInstructor[]>(");
    expect(hookResultNames(instructors.source)).toEqual(expect.arrayContaining(["rosterState", "invitesState"]));
    // 반례 — 타입 인자가 낀 훅의 결과를 효과로 칸에 넣으면 붉어진다.
    const typed = "const roster = useBackendQuery<Row[]>(client, path);\nuseEffect(() => { setName(roster.data[0].name); }, [roster]);";
    expect(effectBodies(typed).some((body) => seedsFromState(body, hookResultNames(typed)))).toBe(true);
    // React 의 훅은 읽은 상태가 아니다.
    expect(hookResultNames("const [title, setTitle] = useState(x);")).toEqual(["state"]);
  });

  it("함수형 갱신은 먼저 친 값(자기 매개변수)을 다시 쓸 때만 통과한다(#691)", () => {
    const names = ["state"];
    expect(seedsFromState('setTitle((c) => (c === "" ? state.problem.title : c));', names)).toBe(false);
    // 반례 둘 — 매개변수가 없거나 쓰지 않으면 옛 버그와 똑같이 덮는다.
    expect(seedsFromState("setTitle(() => state.problem.title);", names)).toBe(true);
    expect(seedsFromState("setTitle((c) => state.problem.title);", names)).toBe(true);
  });

  it("타이머는 setter 가 아니다 — 콜백이 상태를 읽어도 통과한다(#695)", () => {
    const names = ["state"];
    for (const timer of ["setTimeout", "setInterval", "setImmediate"]) {
      expect(seedsFromState(`${timer}(() => reload(state.id), 100);`, names), timer).toBe(false);
    }
    // 반례 — 타이머 안의 진짜 setter 는 여전히 잡는다.
    expect(seedsFromState("setTimeout(() => setTitle(state.problem.title), 100);", names)).toBe(true);
  });

  it("본문이 표현식인 효과도 본다(#691)", () => {
    const rows = SCREENS.find((s) => s.file.endsWith(path.join("components", "ChecklistRows.tsx")))!;
    const expression = "useEffect(() => setRows(items), [signature]);";
    expect(rows.source).toContain(expression);
    // 반례 — 같은 자리에 읽은 상태를 넣으면 붉어진다.
    const seeded = rows.source.replace(expression, "useEffect(() => setRows(state.items), [state]);");
    expect(effectBodies(seeded).some((body) => seedsFromState(body, hookResultNames(seeded)))).toBe(true);
  });

  it("문제 편집 화면은 문제를 읽은 그 렌더에서 칸을 맞춘다", () => {
    const page = SCREENS.find((s) => s.file.endsWith(path.join("[problemId]", "page.tsx")))!;
    expect(page.source).toMatch(/state\.problem\s*!==\s*\w+/);
  });
});
