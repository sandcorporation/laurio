// 런타임 설정을 읽는 화면은 빌드 시점에 구워지면 안 된다 (#297).
//
// **실제로 배포를 망가뜨렸다.** `app/login/page.tsx` 는 `CODEMIT_WEB_ORIGIN` 을 읽어
// 공개 앱의 로그인 주소를 만드는데, `searchParams`·`cookies`·`headers` 를 하나도
// 읽지 않아 Next 가 정적으로 판정했다. `next build` 시점에는 그 환경변수가 없으므로
// **dev 폴백(`http://127.0.0.1:53000`)이 HTML 에 박제되어** 1년 캐시로 서빙됐다
// (`x-nextjs-prerender: 1`, `cache-control: s-maxage=31536000`). 배포된 강의실에서
// 로그인이 아예 불가능했다.
//
// **어떤 게이트도 못 잡았다**: dev 는 매 요청 렌더라 폴백이 안 보이고, CI e2e 는 그
// 스택에서 그 값이 비어 있어 폴백이 「맞는 답」이라 통과하고, deploy-guard 는 부팅
// 여부만 봤다. 프로덕션 빌드에 배포 설정을 실제로 물려야만 드러난다.
//
// 그래서 두 곳에서 잡는다. 여기(로컬 게이트)는 **구조**를 본다 — 런타임 환경변수를
// 읽는 모듈에 닿는 page/route 는 `dynamic = "force-dynamic"` 을 선언해야 한다.
// CI 의 `classroom-deploy-guard` 는 **결과**를 본다 — 실제로 구운 이미지의 /login
// HTML 에 로컬호스트가 없는지.
//
// `NEXT_PUBLIC_*` 는 대상이 아니다 — 그것은 빌드 시점에 번들에 박히는 것이 계약이다.
import * as fs from "node:fs";
import * as path from "node:path";

import { describe, expect, it } from "vitest";

const APP_ROOT = path.resolve(__dirname, "..", "..");
const SCAN_DIRS = ["app", "lib"];
// robots.ts·sitemap.ts(#395)도 Next 파일 컨벤션 진입점이다 — 둘 다
// `CODEMIT_CLASSROOM_ORIGIN`(`lib/seo/origin.ts`)을 읽으므로 대상에 넣지
// 않으면 이 검사가 그 두 라우트를 조용히 지나친다.
const ENTRY_BASENAMES = ["page.tsx", "route.ts", "layout.tsx", "robots.ts", "sitemap.ts"];

/** `process.env.X` — 단, NEXT_PUBLIC_ 은 빌드 시점 주입이 계약이므로 뺀다. */
const RUNTIME_ENV = /process\.env\.(?!NEXT_PUBLIC_)([A-Z0-9_]+)/g;
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

describe("런타임 설정을 읽는 화면은 정적으로 구워지지 않는다 (#297)", () => {
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
          `빌드 시점 값이 HTML 에 박제된다(#297 이 실제로 그렇게 깨졌다).\n닿는 값:\n${why}`,
      ).toBe(true);
    });
  }
});
