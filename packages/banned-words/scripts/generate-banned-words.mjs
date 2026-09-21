#!/usr/bin/env node
// 백엔드의 금칙어 목록(`backend/core/banned_words.py`)에서 TypeScript 목록을
// 생성한다(spec #474, #475/#476, ADR-0051 — 왜 사본 둘이 아니라 생성물인지).
//
// 손으로 쓰지 않는다 — 반드시 어긋나기 때문이다. `pnpm generate` 하나로 돈다.
//
// **스택이 필요 없다.** `export_banned_words`는 순수 파이썬 모듈을 읽어들일 뿐
// DB에 접속하지 않는다(`packages/bff-client/scripts/generate-api-types.mjs`와
// 같은 전제) — `uv sync`만 된 신선한 체크아웃에서도 돈다.
//
// 절차:
//   1. `uv run python manage.py export_banned_words`로 백엔드에서 목록을
//      JSON으로 뽑는다.
//   2. 그 JSON을 그대로 `src/generated/banned-words.gen.ts`에 타입이 붙은
//      TypeScript 배열 리터럴로 써낸다.
//
// CI(`banned-words-generated` 잡)는 이 스크립트를 그대로 돌린 뒤
// `git diff --exit-code`로 커밋된 산출물과 다르면 실패시킨다.

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const packageRoot = path.resolve(__dirname, "..");
const backendRoot = path.resolve(packageRoot, "..", "..", "backend");
const outputFile = path.resolve(packageRoot, "src", "generated", "banned-words.gen.ts");

function run(command, args, options) {
  console.log(`$ ${command} ${args.join(" ")}`);
  execFileSync(command, args, { stdio: "inherit", ...options });
}

const tmpDir = mkdtempSync(path.join(tmpdir(), "codemit-banned-words-"));
const wordsJsonPath = path.join(tmpDir, "banned-words.json");

try {
  console.log("1/2 백엔드에서 금칙어 목록을 내보낸다 (스택 기동 불필요, uv만 있으면 된다)");
  run("uv", ["run", "python", "manage.py", "export_banned_words", "--output", wordsJsonPath], {
    cwd: backendRoot,
  });

  console.log("2/2 목록에서 TypeScript 배열을 생성한다");
  const words = JSON.parse(readFileSync(wordsJsonPath, "utf-8"));

  const renderList = (list) =>
    `[\n${list.map((word) => `  ${JSON.stringify(word)},`).join("\n")}\n]`;

  const output = [
    "// 이 파일은 생성됩니다 — 손으로 고치지 마세요.",
    "// `pnpm --dir packages/banned-words generate` 로 backend/core/banned_words.py 에서",
    "// 다시 만듭니다(ADR-0051). CI가 이 파일이 최신인지 확인합니다(재생성 후 diff가 나면 실패).",
    "",
    "/** 운영진을 사칭하는 낱말 — 이름에만 적용한다. 원본:",
    " * `backend/core/banned_words.py`의 `IMPERSONATION_WORDS`. */",
    `export const IMPERSONATION_WORDS: readonly string[] = ${renderList(words.impersonation)};`,
    "",
    "/** 욕설 — 이름·제목·본문 어디든 적용한다. 원본:",
    " * `backend/core/banned_words.py`의 `PROFANITY_WORDS`. */",
    `export const PROFANITY_WORDS: readonly string[] = ${renderList(words.profanity)};`,
    "",
  ].join("\n");

  writeFileSync(outputFile, output);
  console.log(`written: ${path.relative(packageRoot, outputFile)}`);
} finally {
  rmSync(tmpDir, { recursive: true, force: true });
}
