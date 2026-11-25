// 세 앱의 단추는 진행 중(저장·제출·불러오는 중)에 `disabled` 속성을 쓰지 않는다 — `disabled` 로 바뀌는 순간 눌린 단추의
// 초점이 BODY 로 떨어진다(#1517). `aria-disabled` 를 쓰고 누름은 BusyGuard(packages/bff-client) 가 막는다.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = resolve(__dirname, "../../..");
const APPS = ["frontend/app", "classroom/app", "operator/app", "operator/lib", "classroom/lib", "packages/bff-client/src"];
// 이 낱말이 든 식으로 `<button disabled={…}>` 가 꺼지면 진행 중 단추다.
const BUSY = /\b(saving|submitting|pending|busy|sending|loading|loadingMore|uploading|isSaving|deleting|revealing)\b/;
// 다른 작업자(1517a/b·1518b)가 맡은 파일 — 거기 남은 것은 PR 본문 목록에 있다.
const OTHER_TICKETS = [
  "settings/page",
  "ProblemSideActions",
  "MarkdownEditor",
];

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name === ".next") continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (path.endsWith(".tsx")) out.push(path);
  }
  return out;
}

/** `<button …>` 열린 태그들(속성 안의 `{}` 를 세어 끝을 찾는다). */
function buttonTags(source: string): { tag: string; index: number }[] {
  const found: { tag: string; index: number }[] = [];
  for (const m of source.matchAll(/<button\b/g)) {
    let depth = 0;
    let i = m.index!;
    for (; i < source.length; i++) {
      const c = source[i];
      if (c === "{") depth++;
      else if (c === "}") depth--;
      else if (c === ">" && depth === 0 && source[i - 1] !== "=") break;
    }
    found.push({ tag: source.slice(m.index!, i), index: m.index! });
  }
  return found;
}

describe("진행 중 단추", () => {
  it("disabled 가 아니라 aria-disabled 를 쓴다", () => {
    const offenders: string[] = [];
    for (const app of APPS) {
      for (const file of walk(join(ROOT, app))) {
        const rel = relative(ROOT, file);
        if (OTHER_TICKETS.some((name) => rel.includes(name))) continue;
        const source = readFileSync(file, "utf8");
        for (const { tag, index } of buttonTags(source)) {
          for (const m of tag.matchAll(/(?<![\w-])disabled=\{/g)) {
            let depth = 1;
            let i = m.index! + m[0].length;
            for (; depth > 0; i++) depth += (tag[i] === "{" ? 1 : 0) - (tag[i] === "}" ? 1 : 0);
            const expr = tag.slice(m.index! + m[0].length, i - 1);
            if (BUSY.test(expr)) offenders.push(`${rel}:${source.slice(0, index).split("\n").length} disabled={${expr.trim()}}`);
          }
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});
