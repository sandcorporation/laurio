// 런타임 설정을 읽는 화면은 빌드 시점에 구워지면 안 된다 (#297, #375).
//
// **강의실이 실제로 이렇게 배포를 망가뜨렸다**(`classroom/lib/rendering/
// runtime-config.test.ts`, `classroom/app/login/page.tsx`) — `searchParams`·
// `cookies`·`headers`를 하나도 읽지 않는 화면은 Next가 빌드 시점에 정적으로
// 굽고, 그러면 `process.env`를 읽는 함수가 **빌드 머신의** 값(=비어 있음)을
// 읽어 dev 폴백이 HTML에 박제된다. 공개 앱은 헤더의 계정 메뉴가 `CODEMIT_
// CLASSROOM_ORIGIN`을 그렇게 읽는다(#375, `lib/auth/classroom-link.ts`) —
// 강의실과 같은 실패가 여기서도 가능해진 순간부터 같은 검사가 필요해졌다.
//
// **강의실판을 그대로 옮기지 않는다.** 강의실은 모든 화면이 인증 구역이라
// "런타임 환경변수를 읽으면 예외 없이 force-dynamic"이 성립하지만, 공개 앱은
// `CODEMIT_API_BASE_URL`(`lib/api/client.ts`)을 다섯 공개 화면 전부가 이미
// 읽는다 — 그 화면들은 백엔드 fetch 자체가 매 요청 데이터를 필요로 해
// 이미 사실상 동적이고(ADR-0015는 서버 렌더링을 요구할 뿐 빌드 시점 정적
// 프리렌더를 요구하지 않는다), 이 티켓의 범위도 아니다. 그래서 이 파일은
// **이 티켓이 새로 얹은 값**(계정 메뉴가 읽는 형제 오리진 설정)만 겨냥한다 —
// 대상 목록이 늘면 여기에 추가한다.
//
// 여기(로컬 게이트)는 **구조**를 본다 — 이 값을 읽는 모듈에 닿는
// page/route/layout은 `dynamic = "force-dynamic"`을 선언해야 한다.
import * as fs from "node:fs";
import * as path from "node:path";

import { describe, expect, it } from "vitest";

const APP_ROOT = path.resolve(__dirname, "..", "..");
const SCAN_DIRS = ["app", "lib"];
// robots.ts·sitemap.ts(#394)도 Next 파일 컨벤션 진입점이다 — 둘 다
// `CODEMIT_WEB_ORIGIN`(`lib/seo/origin.ts`)을 읽으므로 대상에 넣지 않으면 이
// 검사가 그 두 라우트를 조용히 지나친다.
const ENTRY_BASENAMES = ["page.tsx", "route.ts", "layout.tsx", "robots.ts", "sitemap.ts"];

/** 이 티켓이 헤더 경로에 새로 얹은 런타임 설정 — 대상 목록이 늘면 여기에
 * 추가한다. 공개 설정(`CODEMIT_PUBLIC_*`)은 루트 레이아웃이 읽고, 그 레이아웃이
 * `force-dynamic` 인 것은 `lib/public-config.test.ts` 가 본다(#711). */
const WATCHED_RUNTIME_ENV = ["CODEMIT_CLASSROOM_ORIGIN"];
const RUNTIME_ENV = new RegExp(`process\\.env\\.(${WATCHED_RUNTIME_ENV.join("|")})`, "g");
const FORCE_DYNAMIC = /export\s+const\s+dynamic\s*=\s*["']force-dynamic["']/;
const IMPORT_FROM = /(?:^|\n)\s*import[^"']*["']([^"']+)["']/g;

function walk(dir: string): string[] {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) return e.name === "node_modules" ? [] : walk(full);
    return /\.tsx?$/.test(e.name) && !e.name.endsWith(".test.ts") ? [full] : [];
  });
}

/** `@/lib/x` 와 `./x` 를 실제 파일 경로로 푼다. 앱 밖(패키지)은 null. */
function resolveImport(fromFile: string, spec: string): string | null {
  let base: string;
  if (spec.startsWith("@/")) base = path.join(APP_ROOT, spec.slice(2));
  else if (spec.startsWith(".")) base = path.resolve(path.dirname(fromFile), spec);
  else return null;
  for (const cand of [base, `${base}.ts`, `${base}.tsx`, path.join(base, "index.ts")]) {
    if (fs.existsSync(cand) && fs.statSync(cand).isFile()) return cand;
  }
  return null;
}

const FILES = SCAN_DIRS.flatMap((d) => walk(path.join(APP_ROOT, d)));
const SOURCE = new Map(FILES.map((f) => [f, fs.readFileSync(f, "utf8")]));

function readsRuntimeEnv(file: string): string[] {
  return [...(SOURCE.get(file) ?? "").matchAll(RUNTIME_ENV)].map((m) => m[1]);
}

/** file 이 (자신 포함, 임포트를 따라) 닿는 런타임 환경변수 전부. */
function reachedRuntimeEnv(entry: string): Map<string, string> {
  const found = new Map<string, string>(); // 변수 -> 그것을 읽는 파일
  const seen = new Set<string>();
  const stack = [entry];
  while (stack.length) {
    const cur = stack.pop()!;
    if (seen.has(cur)) continue;
    seen.add(cur);
    for (const v of readsRuntimeEnv(cur)) if (!found.has(v)) found.set(v, cur);
    for (const m of (SOURCE.get(cur) ?? "").matchAll(IMPORT_FROM)) {
      const next = resolveImport(cur, m[1]);
      if (next) stack.push(next);
    }
  }
  return found;
}

describe("런타임 설정을 읽는 화면은 정적으로 구워지지 않는다 (#297, #375)", () => {
  const entries = FILES.filter((f) => ENTRY_BASENAMES.includes(path.basename(f)));

  it("훑을 진입점이 실제로 있다 — 경로가 바뀌면 이 검사가 조용히 빈손이 된다", () => {
    expect(entries.length).toBeGreaterThan(5);
  });

  for (const entry of entries) {
    const rel = path.relative(APP_ROOT, entry);
    it(`${rel}`, () => {
      const reached = reachedRuntimeEnv(entry);
      if (reached.size === 0) return; // 런타임 설정을 안 읽으면 정적이어도 좋다
      const why = [...reached]
        .map(([v, f]) => `  ${v} (${path.relative(APP_ROOT, f)})`)
        .join("\n");
      expect(
        FORCE_DYNAMIC.test(SOURCE.get(entry) ?? ""),
        `${rel} 는 런타임 환경변수를 읽는데 \`export const dynamic = "force-dynamic"\` 이 없다.\n` +
          `빌드 시점 값이 HTML 에 박제된다(#297 이 강의실에서 실제로 그렇게 깨졌다).\n닿는 값:\n${why}`,
      ).toBe(true);
    });
  }
});
