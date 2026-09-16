// 브랜드가 다시 갈라지면 **기계가 막는다** (#370, 부모 #358).
//
// 공개 앱과 강의실은 `app/tokens.css` 를 한 글자도 다르지 않게 공유하고
// (`classroom/lib/design/tokens.test.ts` 가 그것을 강제한다), 이 파일은 그
// 토큰이 화면에서 실제로 **지켜지는지**를 본다. 갈라짐은 조용하다:
//
// - **정의된 적 없는 색**을 부르면 Tailwind 는 오류 없이 **아무 것도 만들지
//   않는다.** `bg-accent text-white` 는 배경 없는 흰 글자가 되어 버튼이 통째로
//   보이지 않았다(#366 이 72자리에서 겪은 실패).
// - **토큰 반경 스케일을 우회하는 모서리**는 조용히 다른 모양을 낸다.
//   `rounded-full` 은 `calc(infinity * 1px)`, 맨 `rounded` 는 0.25rem 이라 둘 다
//   `--radius-*`(0–2px)를 읽지 않는다.
//
// **새 CI 잡을 만들지 않는다** — 이미 도는 순수 함수 시임(ADR-0026)에 얹는다.
// 이 러너는 react·next 임포트를 거부하지만 파일 읽기는 막지 않으므로 소스를
// **텍스트로** 훑는다.
//
// **운영자 앱도 대상이다**(#422, 부모 #421) — `operator/app/tokens.css` 가
// 생기고 골간·지급 큐가 유틸리티 클래스를 쓰기 시작했다. #426 이 운영자
// 계정·신고된 템플릿·무료 공모전을 더 옮겼다. 아직 옮기지 않은 화면
// 다섯(정책·카테고리·산출물 종류·개최 권한·로그인)은 여전히 요소 스킨
// (`operator/app/globals.css`)이라 유틸리티 클래스가 없고, 이 검사가 훑어도
// 걸릴 것이 없다.
//
// **무엇을 읽는가.** 클래스는 세 모양으로 조립된다 — 정적 속성, 템플릿 리터럴
// 안의 조건식(`${ok ? "bg-verified" : "bg-attention"}`), 그리고
// `lib/ui/classnames.ts` 같은 상수. `className="…"` 만 쫓으면 뒤의 둘을 놓치고,
// 속성을 잘라 공백으로 쪼개면 조건식의 따옴표가 토큰에 남는다(처음에 그렇게
// 결백한 `bg-verified"` 를 신고했다). 그래서 **주석을 걷어낸 뒤 모든 문자열
// 리터럴**을 꺼내, 그 안에서 유틸리티 모양의 낱말만 검사한다. 주석을 먼저 걷는
// 이유는 주석 속 `rounded` 같은 낱말이 백틱에 싸여 리터럴처럼 잡히기 때문이다.
import * as fs from "node:fs";
import * as path from "node:path";

import { describe, expect, it } from "vitest";

const FRONTEND = path.resolve(__dirname, "..", "..");
const REPO = path.resolve(FRONTEND, "..");
const SCANNED_DIRS = [
  "frontend/app",
  "frontend/lib",
  "classroom/app",
  "classroom/lib",
  "operator/app",
  "operator/lib",
].map((d) => path.join(REPO, d));

/** 이 브랜드의 색은 정확히 여섯이다(`app/tokens.css` 의 `@theme`). */
const DEFINED_COLORS = new Set(["ink", "paper", "surface", "rule", "attention", "verified"]);

/** `--radius-*` 를 읽는 반경들. 맨 `rounded` 와 `rounded-full` 은 여기 없다. */
const TOKEN_RADII = new Set([
  "rounded-none", "rounded-xs", "rounded-sm", "rounded-md",
  "rounded-lg", "rounded-xl", "rounded-2xl", "rounded-3xl", "rounded-4xl",
]);

/** 토큰 반경을 우회해도 되는 **유일한** 자리 — 알림 벨의 읽지 않은 수 배지.
 *  숫자 하나를 담는 표식은 원이어야 「세어 볼 것」으로 읽힌다는 판단이다(2026-09-13,
 *  사용자 결정). 그래서 브랜드의 각진 규칙에서 이 한 모양만 뺀다 — 예외를 파일
 *  단위로 좁혀 두어, 다른 화면에 `rounded-full` 이 번지면 여전히 빨개진다. */
const ROUND_BADGE_FILES = new Set([
  "frontend/app/components/notification-bell.tsx",
  "classroom/app/components/notification-bell.tsx",
]);

/** 색이 올 수 있는 접두어. 뒤가 늘 색은 아니라 `isNotAColor` 가 한 번 더 거른다. */
const COLOR_PREFIXES = new Set([
  "bg", "text", "border", "ring", "divide", "outline",
  "accent", "placeholder", "caret", "decoration", "fill", "stroke",
]);

/** 색이 아닌 값 — 크기·정렬·변·선 모양·키워드. */
const NOT_COLORS = new Set([
  "xs", "sm", "base", "lg", "xl", "2xl", "3xl", "4xl", "5xl",
  "left", "center", "right", "justify", "start", "end",
  "ellipsis", "clip", "nowrap", "wrap", "balance", "pretty",
  "none", "solid", "dashed", "dotted", "double", "hidden", "collapse", "separate",
  "transparent", "current", "inherit", "auto",
  "x", "y", "t", "b", "l", "r", "s", "e",
]);

function isNotAColor(value: string): boolean {
  if (NOT_COLORS.has(value)) return true;
  if (/^\d/.test(value)) return true; // border-2 · outline-2 · border-b-0
  if (value.startsWith("[")) return true; // 임의값 — text-[13px] · bg-[…var(--color-rule)…]
  if (value.startsWith("offset-")) return true; // outline-offset-2
  return false;
}

function sourceFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    if (!fs.existsSync(dir)) return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === "node_modules" || entry.name === "__snapshots__") continue;
        walk(full);
      } else if (/\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) {
        out.push(full);
      }
    }
  };
  SCANNED_DIRS.forEach(walk);
  return out;
}

/** 주석 줄(`//`·`*`·`/*`)과 JSX 주석(`{/* … *\/}`)을 걷는다. */
export function stripComments(source: string): string {
  return source
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .split("\n")
    .filter((line) => !/^\s*(\/\/|\/\*|\*)/.test(line))
    .join("\n");
}

/** 문자열 리터럴 전부 — 조립 방식(속성·조건식·상수)과 무관하게. */
function stringLiterals(source: string): string[] {
  const found: string[] = [];
  for (const m of source.matchAll(/"([^"\n]*)"/g)) found.push(m[1]);
  for (const m of source.matchAll(/'([^'\n]*)'/g)) found.push(m[1]);
  // 템플릿 리터럴은 보간식 `${…}` 을 걷고 읽는다 — 그 안은 JS 식이라 변수 이름
  // (`rounded` 같은)이 섞이고, 식 속 클래스 문자열은 위 따옴표 리터럴로 이미 잡힌다.
  for (const m of source.matchAll(/`([^`]*)`/g)) found.push(m[1].replace(/\$\{[^}]*\}/g, " "));
  return found;
}

/** Tailwind 유틸리티 모양인가. 대괄호가 열린 채 쪼개진 임의값 조각은 뺀다. */
function looksLikeUtility(token: string): boolean {
  if (!/^[a-z0-9:[\]/.%_-]+$/.test(token)) return false;
  return (token.match(/\[/g) ?? []).length === (token.match(/\]/g) ?? []).length;
}

/** 이 유틸리티가 브랜드를 벗어나면 그 이유, 아니면 null. */
export function violationOf(raw: string): string | null {
  if (!looksLikeUtility(raw)) return null;

  // 다크 값은 tokens.css 의 `light-dark()` 에만 둔다(#397) — 컴포넌트가
  // `dark:` 변형을 쓰면 그 자리 하나가 토큰 밖에서 테마를 갈라 다시 흩어진다.
  if (raw.split(":").slice(0, -1).includes("dark")) {
    return "다크 값은 tokens.css 에서만 정한다 — 컴포넌트 밖에서 `dark:` 변형을 쓰지 않는다";
  }

  const utility = raw.slice(raw.lastIndexOf(":") + 1); // hover:·sm:·group-hover: 를 벗긴다

  if (utility === "rounded" || utility.startsWith("rounded-")) {
    return TOKEN_RADII.has(utility.split("/")[0])
      ? null
      : "토큰이 정한 모서리 스케일(--radius-*, 0–2px)을 읽지 않는다";
  }

  const dash = utility.indexOf("-");
  if (dash === -1 || !COLOR_PREFIXES.has(utility.slice(0, dash))) return null;
  let value = utility.slice(dash + 1).split("/")[0]; // 투명도 접미사를 뗀다
  if (utility.startsWith("border-") && /^[btlrxyse]-/.test(value)) value = value.slice(2); // border-b-surface
  if (isNotAColor(value) || DEFINED_COLORS.has(value)) return null;
  return `정의된 적 없는 색 이름이다 — 이 브랜드의 색은 ${[...DEFINED_COLORS].join("·")} 여섯뿐이다`;
}

function scan(): string[] {
  const report: string[] = [];
  for (const file of sourceFiles()) {
    const rel = path.relative(REPO, file);
    for (const literal of stringLiterals(stripComments(fs.readFileSync(file, "utf8")))) {
      for (const raw of literal.split(/\s+/)) {
        if (raw === "rounded-full" && ROUND_BADGE_FILES.has(rel)) continue;
        const why = raw && violationOf(raw);
        if (why) report.push(`  ${rel}: \`${raw}\` — ${why}`);
      }
    }
  }
  return report;
}

describe("브랜드는 기계가 지킨다 (#370)", () => {
  it("훑을 소스를 실제로 찾는다 — 경로가 바뀌면 이 검사가 조용히 빈손이 된다", () => {
    expect(sourceFiles().length).toBeGreaterThan(100);
  });

  // 이 검사는 두 앱의 소스 281개(약 1.3MB)를 읽는다 — 이 머신에서는 40~50ms 지만,
  // CI 는 e2e·deploy-guard 잡이 같은 러너에서 동시에 도는 공유 머신이라 같은 읽기가
  // 5초(vitest 기본값)를 넘긴 적이 있다(2026-09-16, 재실행에서는 42ms 로 통과 —
  // 코드 회귀가 아니라 부하였다). 그 실패는 「브랜드가 깨졌다」와 구분되지 않으므로
  // 제한을 넉넉히 준다.
  it("정의되지 않은 색도, 토큰을 우회하는 모서리도 없다", () => {
    const report = scan();
    expect(report, `브랜드를 벗어난 클래스 ${report.length}건:\n${report.join("\n")}`).toEqual([]);
  }, 60_000);

  it("검사 자체가 살아 있다 — 위반을 넣으면 실제로 잡는다", () => {
    // 초록인 것만으로는 「지킨다」와 「아무것도 안 본다」가 구별되지 않는다.
    const caught = [
      "bg-accent",
      "text-white",
      "rounded-full",
      "rounded",
      "hover:border-subtle",
      "dark:text-paper",
    ].filter((t) => violationOf(t) !== null);
    expect(caught).toEqual([
      "bg-accent",
      "text-white",
      "rounded-full",
      "rounded",
      "hover:border-subtle",
      "dark:text-paper",
    ]);
  });

  it("허용해야 할 것은 막지 않는다 — 크기·변·투명도·임의값·토큰 반경", () => {
    const allowed = [
      "text-sm", "text-ink/60", "border-b", "border-b-surface", "border-l-2", "bg-transparent",
      "text-[13px]", "outline-offset-2", "divide-y", "rounded-sm", "hover:bg-attention/5",
    ];
    expect(allowed.filter((t) => violationOf(t) !== null)).toEqual([]);
  });

  it("템플릿 리터럴 보간식 속 변수 이름은 클래스가 아니다", () => {
    const source = "const s = `${Number.isInteger(rounded) ? rounded : 1}MB`;";
    expect(stringLiterals(source).flatMap((l) => l.split(/\s+/)).filter((t) => t && violationOf(t))).toEqual([]);
  });

  it("동그란 배지 예외는 알림 벨 두 파일에만 열려 있고, 그 파일들이 실제로 있다", () => {
    for (const rel of ROUND_BADGE_FILES) expect(fs.existsSync(path.join(REPO, rel)), rel).toBe(true);
    expect(ROUND_BADGE_FILES.size).toBe(2);
  });

  it("주석 속 낱말은 클래스가 아니다", () => {
    const source = "// 이 파일은 `rounded`류 유틸리티를 쓰지 않는다\nconst x = 1;";
    expect(stringLiterals(stripComments(source))).toEqual([]);
  });
});
