// 고아 라우트 탐지(#166) — 정적 분석, 스택 불필요.
//
// #164·#165는 같은 버그의 두 사례였다: 화면은 있고 API도 잘 도는데 제품 안에서
// 아무도 링크하지 않는다. e2e·백엔드 테스트 둘 다 이걸 못 본다 — `page.goto(...)`로
// URL을 직접 치는 테스트는 원리적으로 "사람이 거기 도달할 수 있는가"를 보지 않는다.
//
// **공유 워크스페이스 패키지에 두는 이유**: 이 규칙은 공개 앱·운영자 앱 둘 다 같은
// 정의를 써야 한다 — 한쪽만 스캐너를 고치면 두 앱이 조용히 다른 기준으로 갈리고,
// 그건 이 검사가 막으려는 것과 같은 종류의 문제("조용히 갈라지는 것")다. `packages/
// bff-shared`에 얹지 않은 이유는 그 패키지가 BFF 런타임(프록시 전달·Origin 검증)
// 성격이 뚜렷해서다 — 빌드 시점 정적 분석 도구를 거기 섞으면 그 패키지의 경계가
// 흐려진다. 대신 ADR-0021이 이미 세운 선례(`packages/bff-shared`·`packages/
// bff-client`)를 그대로 따라 새 워크스페이스 패키지(`@codemit/route-audit`)를 둔다.
// 앱마다 남는 것은 두 가지뿐이다 — 어느 디렉터리를 훑는지(`orphan-suite.ts`의
// `appRoot`), 그리고 그 앱의 허용목록(`lib/routes/allowlist.ts`).
//
// 이 파일은 두 가지를 한다:
//   1. `app/**/page.tsx`(또는 `page.ts`)에서 라우트 목록을 만든다.
//   2. 소스 전체(TypeScript AST, `typescript` 컴파일러 API)에서 링크를 내는
//      표현을 모은다 — JSX `href` 속성, 객체 리터럴의 `href` 프로퍼티(네비게이션
//      설정 배열), `.push(...)`/`.replace(...)`(라우터), `redirect(...)`/
//      `redirectToPath(...)`, `new URL(...)`(미들웨어의 리다이렉트 목적지).
// 그 뒤 동적 세그먼트(`[param]`)와 템플릿 보간(`${...}`)을 같은 자리표로 정규화해
// 라우트와 링크를 세그먼트 단위로 대조한다. 인바운드 링크가 하나도 없는 라우트가 고아다.
//
// **정규식 대신 AST를 쓰는 이유**: 문자열 리터럴과 정규식 리터럴은 컴파일러가 이미
// 구분해 준다 — `value.replace(/\D/g, "")` 같은 `String.prototype.replace` 호출이
// `router.replace("/path")`로 오탐되지 않는다(리터럴 노드 종류 자체가 다르다).
//
// **알려진 한계 — 조용히 통과시키는 대신 여기 적는다:**
//   - **변수로 조립된 경로는 함수 호출과 지역 변수 각 1홉만 되짚는다**(`MAX_RESOLUTION_DEPTH`
//     로 상한). 같은 파일 안의 지역 함수(`function`/`const f = () => ...`)나 지역
//     `const` 변수 하나를 통해 문자열까지 도달하면 잡지만, 그보다 깊은 데이터 흐름
//     (다른 파일에서 값을 받아오거나, 배열/객체를 순회하며 조립하는 경우)은 못 본다.
//   - **`route.ts`(라우트 핸들러)는 라우트 목록에 넣지 않는다.** 이건 사람이 브라우저로
//     "도달"하는 화면이 아니라 fetch로 호출되는 API라 진입점 개념 자체가 다르다
//     (`/api/backend/[...path]` 같은 프록시는 애초에 페이지가 아니다).
//   - **route group(`(name)`)과 parallel route slot(`@name`)은 URL에서 제거**하지만,
//     intercepting route 접두어(`(.)`·`(..)`·`(...)`, 이 저장소에는 아직 없다)는 다루지
//     않는다 — 세그먼트 전체가 괄호로 감싸이지 않아 route group 정규식과 겹치지 않기
//     때문에, 생기면 정적 세그먼트로 오인해 오탐(고아 아님으로 잘못 판정)할 수 있다.
//   - **optional catch-all(`[[...slug]]`)은 "부모 경로 자체도 같은 페이지"라는 Next의
//     규칙을 모른다** — 이 저장소에는 아직 그런 라우트가 없다.
//   - **객체 리터럴·배열 인자는 재귀하지 않는다**(`.push({...})`처럼 배열에 데이터를
//     쌓는 흔한 호출과 라우터 네비게이션을 같은 이름만으로 구분할 수 없어서다) — 그래서
//     라우팅과 무관한 `.push`/`.replace` 호출은 후보를 아예 못 낸다(안전한 방향의
//     누락이다: 그 호출이 실제로 경로 문자열을 첫 인자로 준다면 여전히 잡힌다).
import * as fs from "node:fs";
import * as path from "node:path";
import * as ts from "typescript";

// 소스 텍스트에 나타날 일이 없는 문자 — 템플릿 보간(`${...}`) 자리를 표시한다.
const PLACEHOLDER = "";
const MAX_RESOLUTION_DEPTH = 3;
const PAGE_FILENAMES = new Set(["page.tsx", "page.ts"]);
const DEFAULT_EXCLUDED_DIR_NAMES = new Set([
  "node_modules",
  ".next",
  ".git",
  "e2e",
  "coverage",
  "dist",
  "build",
]);

export type RouteSegment =
  | { kind: "static"; value: string }
  | { kind: "dynamic" }
  | { kind: "catchall"; optional: boolean };

export interface RouteEntry {
  /** 정규화 전 라우트 경로. 예: "/console/contests/[contestId]/submit" */
  display: string;
  segments: RouteSegment[];
}

export interface LinkSegment {
  text: string;
  dynamic: boolean;
}

// 의도적으로 인바운드 링크가 없는 라우트 한 건. 목록의 **내용**(경로 문자열과 이유)은
// `packages/bff-shared`의 허용목록 선례와 같은 이유로 이 파일에 두지 않는다 — 각 앱이
// 자기 `lib/routes/allowlist.ts`에 갖는다. 여기서는 타입만 정의해 두 앱이 같은 모양을
// 쓰도록 강제한다.
export interface OrphanAllowlistEntry {
  /** 정규화 전 라우트 경로. RouteEntry.display와 정확히 같은 형식. */
  route: string;
  reason: string;
}

// ---------------------------------------------------------------------------
// 1) app/**/page.tsx → 라우트 목록
// ---------------------------------------------------------------------------

export function listPageRoutes(appDir: string): RouteEntry[] {
  const routes: RouteEntry[] = [];
  walkPages(appDir, appDir, routes);
  return routes;
}

function walkPages(dir: string, root: string, out: RouteEntry[]): void {
  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (DEFAULT_EXCLUDED_DIR_NAMES.has(entry.name)) continue;
      walkPages(full, root, out);
    } else if (entry.isFile() && PAGE_FILENAMES.has(entry.name)) {
      const relDir = path.relative(root, dir);
      out.push(buildRouteEntry(relDir));
    }
  }
}

function buildRouteEntry(relDir: string): RouteEntry {
  const rawSegments = relDir === "" ? [] : relDir.split(path.sep);
  const segments: RouteSegment[] = [];
  const displayParts: string[] = [];

  for (const seg of rawSegments) {
    if (/^\(.+\)$/.test(seg)) continue; // route group — URL에 안 나온다
    if (/^@/.test(seg)) continue; // parallel route slot — URL에 안 나온다

    const optionalCatchall = seg.match(/^\[\[\.\.\.(.+)\]\]$/);
    const catchall = seg.match(/^\[\.\.\.(.+)\]$/);
    const dynamic = seg.match(/^\[(.+)\]$/);

    if (optionalCatchall) {
      segments.push({ kind: "catchall", optional: true });
      displayParts.push(seg);
    } else if (catchall) {
      segments.push({ kind: "catchall", optional: false });
      displayParts.push(seg);
    } else if (dynamic) {
      segments.push({ kind: "dynamic" });
      displayParts.push(seg);
    } else {
      segments.push({ kind: "static", value: seg });
      displayParts.push(seg);
    }
  }

  return { display: "/" + displayParts.join("/"), segments };
}

// ---------------------------------------------------------------------------
// 2) 소스 전체 → 링크를 내는 문자열(세그먼트 배열로 정규화된 형태)
// ---------------------------------------------------------------------------

export function extractLinkSegments(
  rootDir: string,
  extraExcludedDirNames: string[] = [],
): LinkSegment[][] {
  const excluded = new Set(DEFAULT_EXCLUDED_DIR_NAMES);
  for (const name of extraExcludedDirNames) excluded.add(name);

  const files = collectSourceFiles(rootDir, excluded);
  const out: LinkSegment[][] = [];
  for (const file of files) {
    collectLinksFromFile(file, out);
  }
  return out;
}

function collectSourceFiles(rootDir: string, excludedDirNames: Set<string>): string[] {
  const files: string[] = [];
  walkSources(rootDir, excludedDirNames, files);
  return files;
}

function walkSources(dir: string, excludedDirNames: Set<string>, out: string[]): void {
  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (excludedDirNames.has(entry.name)) continue;
      walkSources(full, excludedDirNames, out);
    } else if (entry.isFile() && (entry.name.endsWith(".ts") || entry.name.endsWith(".tsx"))) {
      if (entry.name.endsWith(".d.ts")) continue;
      out.push(full);
    }
  }
}

interface LocalScope {
  /** 지역 함수 이름 → 그 함수가 낼 수 있는 return 표현식들 */
  returns: Map<string, ts.Expression[]>;
  /** 지역 const/let 변수 이름 → 그 초기화 표현식 (함수 제외) */
  constants: Map<string, ts.Expression>;
}

function collectLinksFromFile(file: string, out: LinkSegment[][]): void {
  const text = fs.readFileSync(file, "utf8");
  const sourceFile = ts.createSourceFile(
    file,
    text,
    ts.ScriptTarget.Latest,
    /* setParentNodes */ true,
    file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );

  const scope = collectLocalScope(sourceFile);
  const addFrom = (node: ts.Node) => {
    for (const pattern of extractPathCandidates(node, scope, 0)) {
      if (!pattern.startsWith("/")) continue;
      out.push(patternToSegments(pattern));
    }
  };

  const visit = (node: ts.Node) => {
    // <Link href="..."> / <Link href={...}> / <a href={...}> — 태그 종류를 가리지 않는다.
    if (ts.isJsxAttribute(node) && ts.isIdentifier(node.name) && node.name.text === "href") {
      const init = node.initializer;
      if (init) {
        if (ts.isStringLiteral(init)) addFrom(init);
        else if (ts.isJsxExpression(init) && init.expression) addFrom(init.expression);
      }
    }

    // 객체 리터럴의 href 프로퍼티(내비게이션 설정 배열 등).
    if (
      ts.isPropertyAssignment(node) &&
      ((ts.isIdentifier(node.name) && node.name.text === "href") ||
        (ts.isStringLiteral(node.name) && node.name.text === "href"))
    ) {
      addFrom(node.initializer);
    }

    // router.push(...) / router.replace(...)
    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      (node.expression.name.text === "push" || node.expression.name.text === "replace") &&
      node.arguments.length > 0
    ) {
      addFrom(node.arguments[0]);
    }

    // redirect(...) / redirectToPath(...) — 임포트 출처를 가리지 않고 이름으로만 잡는다.
    if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      (node.expression.text === "redirect" || node.expression.text === "redirectToPath") &&
      node.arguments.length > 0
    ) {
      addFrom(node.arguments[0]);
    }

    // new URL("/path", ...) — 미들웨어가 리다이렉트 목적지를 짓는 자리.
    if (
      ts.isNewExpression(node) &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === "URL" &&
      node.arguments &&
      node.arguments.length > 0
    ) {
      addFrom(node.arguments[0]);
    }

    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
}

function collectLocalScope(sourceFile: ts.SourceFile): LocalScope {
  const returns = new Map<string, ts.Expression[]>();
  const constants = new Map<string, ts.Expression>();

  const visit = (node: ts.Node) => {
    if (ts.isFunctionDeclaration(node) && node.name && node.body) {
      returns.set(node.name.text, collectReturnExpressions(node.body));
    } else if (ts.isVariableStatement(node)) {
      for (const decl of node.declarationList.declarations) {
        if (!ts.isIdentifier(decl.name) || !decl.initializer) continue;
        const init = decl.initializer;
        if (ts.isArrowFunction(init) || ts.isFunctionExpression(init)) {
          if (ts.isBlock(init.body)) {
            returns.set(decl.name.text, collectReturnExpressions(init.body));
          } else {
            returns.set(decl.name.text, [init.body]);
          }
        } else {
          constants.set(decl.name.text, init);
        }
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);

  return { returns, constants };
}

function isFunctionLikeNode(node: ts.Node): boolean {
  return (
    ts.isFunctionDeclaration(node) ||
    ts.isFunctionExpression(node) ||
    ts.isArrowFunction(node) ||
    ts.isMethodDeclaration(node) ||
    ts.isGetAccessor(node) ||
    ts.isSetAccessor(node)
  );
}

function collectReturnExpressions(body: ts.Node): ts.Expression[] {
  const out: ts.Expression[] = [];
  const visit = (node: ts.Node) => {
    if (node !== body && isFunctionLikeNode(node)) return; // 중첩 함수의 return은 그 함수 몫
    if (ts.isReturnStatement(node) && node.expression) out.push(node.expression);
    ts.forEachChild(node, visit);
  };
  ts.forEachChild(body, visit);
  return out;
}

function extractPathCandidates(node: ts.Node, scope: LocalScope, depth: number): string[] {
  if (depth > MAX_RESOLUTION_DEPTH) return [];

  if (ts.isParenthesizedExpression(node)) {
    return extractPathCandidates(node.expression, scope, depth);
  }
  if (ts.isAsExpression(node) || ts.isSatisfiesExpression(node)) {
    return extractPathCandidates(node.expression, scope, depth);
  }
  if (ts.isStringLiteralLike(node)) {
    return [node.text];
  }
  if (ts.isTemplateExpression(node)) {
    let pattern = node.head.text;
    for (const span of node.templateSpans) {
      pattern += PLACEHOLDER + span.literal.text;
    }
    return [pattern];
  }
  if (ts.isConditionalExpression(node)) {
    return [
      ...extractPathCandidates(node.whenTrue, scope, depth),
      ...extractPathCandidates(node.whenFalse, scope, depth),
    ];
  }
  if (
    ts.isBinaryExpression(node) &&
    (node.operatorToken.kind === ts.SyntaxKind.BarBarToken ||
      node.operatorToken.kind === ts.SyntaxKind.QuestionQuestionToken)
  ) {
    return [
      ...extractPathCandidates(node.left, scope, depth),
      ...extractPathCandidates(node.right, scope, depth),
    ];
  }
  if (
    ts.isNewExpression(node) &&
    ts.isIdentifier(node.expression) &&
    node.expression.text === "URL" &&
    node.arguments &&
    node.arguments.length > 0
  ) {
    return extractPathCandidates(node.arguments[0], scope, depth + 1);
  }
  if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
    const returns = scope.returns.get(node.expression.text);
    if (returns) {
      return returns.flatMap((expr) => extractPathCandidates(expr, scope, depth + 1));
    }
    return [];
  }
  if (ts.isIdentifier(node)) {
    const init = scope.constants.get(node.text);
    if (init) return extractPathCandidates(init, scope, depth + 1);
    return [];
  }
  return [];
}

function patternToSegments(pattern: string): LinkSegment[] {
  const withoutHash = pattern.split("#")[0];
  const withoutQuery = withoutHash.split("?")[0];
  const trimmed = withoutQuery.replace(/^\//, "");
  if (trimmed.length === 0) return [];
  return trimmed.split("/").map((seg) => ({
    text: seg.split(PLACEHOLDER).join(""),
    dynamic: seg.includes(PLACEHOLDER),
  }));
}

// ---------------------------------------------------------------------------
// 3) 대조
// ---------------------------------------------------------------------------

function segmentsMatch(routeSegments: RouteSegment[], linkSegments: LinkSegment[]): boolean {
  let i = 0;
  let j = 0;
  while (i < routeSegments.length) {
    const rs = routeSegments[i];
    if (rs.kind === "catchall") {
      const remaining = linkSegments.length - j;
      return rs.optional ? remaining >= 0 : remaining >= 1;
    }
    if (j >= linkSegments.length) return false;
    const ls = linkSegments[j];
    if (rs.kind === "static" && (ls.dynamic || ls.text !== rs.value)) {
      return false;
    }
    i++;
    j++;
  }
  return j === linkSegments.length;
}

export function findOrphanRoutes(
  routes: RouteEntry[],
  linkSegmentsList: LinkSegment[][],
): RouteEntry[] {
  return routes.filter(
    (route) => !linkSegmentsList.some((link) => segmentsMatch(route.segments, link)),
  );
}
