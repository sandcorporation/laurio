#!/usr/bin/env node
// 백엔드의 OpenAPI 스키마에서 두 앱이 함께 쓰는 타입을 생성한다(FE-03 #28; 패키지로 이사 #146).
//
// 손으로 쓰지 않는다 — 반드시 어긋나기 때문이다. `pnpm generate:api` 하나로 돈다.
//
// **스택이 필요 없다.** django-ninja의 스키마 생성은 등록된 라우터·스키마 클래스를
// 읽어들일 뿐 DB에 접속하지 않으므로(`backend/core/management/commands/
// export_openapi_schema.py` 참고), `docker compose up` 없이 `uv sync` 만 된
// 상태로 신선한 체크아웃에서도 돈다. dev compose 가 떠 있어야 하는 다른 프론트
// 명령들(`pnpm test`)과 이 점이 다르다 — 백엔드 컨테이너를 기다릴 필요가 없어
// CI의 타입 최신성 검사(staleness check)가 더 빠르고 더 안정적이다.
//
// 절차:
//   1. `uv run python manage.py export_openapi_schema` 로 백엔드에서 스키마를
//      뽑아 임시 파일에 쓴다(레포에는 커밋하지 않는다 — 커밋되는 유일한 산출물은
//      아래 2번의 타입 파일이다. 원본 JSON까지 커밋하면 같은 사실을 두 파일이
//      따로 갖게 되어 최신성 검사가 무엇을 기준으로 삼아야 하는지 애매해진다).
//   2. `openapi-typescript` 로 그 스키마를 `src/schema.gen.ts` 로 직접
//      써낸다(`-o`) — Node 프로세스의 stdout으로 전체 산출물을 실어 보내지
//      않는다. 코디네이터 리뷰 지적: 예전엔 stdout으로 받아 우리가 다시
//      파일에 썼는데, `execFileSync` 의 기본 `maxBuffer` (1MiB)가 스키마가
//      자라면서 언젠가 `ENOBUFS` 로 터진다 — 오늘은 128KB라 안 걸렸을 뿐이다.
//      CLI가 파일로 직접 쓰게 하면 그 상한 자체가 없어진다.
//
// CI(`frontend-openapi-types` 잡)는 이 스크립트를 그대로 돌린 뒤
// `git diff --exit-code` 로 커밋된 산출물과 다르면 실패시킨다 — 재생성했을 때
// diff 가 나면 실패한다는 티켓의 요구사항 그대로다.

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const packageRoot = path.resolve(__dirname, "..");
const backendRoot = path.resolve(packageRoot, "..", "..", "backend");
const outputFile = path.resolve(packageRoot, "src", "schema.gen.ts");

function run(command, args, options) {
  console.log(`$ ${command} ${args.join(" ")}`);
  // 세 단계 모두 결과물을 파일로 직접 쓰게 하므로(1단계 --output, 2단계 -o),
  // stdout을 캡처할 이유가 없다 — 그대로 콘솔에 흘려보낸다. 각 도구의 진행
  // 로그(uv/openapi-typescript)가 여기 그대로 찍힌다.
  execFileSync(command, args, { stdio: "inherit", ...options });
}

const tmpDir = mkdtempSync(path.join(tmpdir(), "laurio-openapi-"));
const schemaJsonPath = path.join(tmpDir, "schema.json");

try {
  console.log("1/2 백엔드에서 OpenAPI 스키마를 내보낸다 (스택 기동 불필요, uv만 있으면 된다)");
  run("uv", ["run", "python", "manage.py", "export_openapi_schema", "--output", schemaJsonPath], {
    cwd: backendRoot,
  });

  console.log("2/2 스키마에서 TypeScript 타입을 생성한다");
  const cliPath = path.resolve(packageRoot, "node_modules", "openapi-typescript", "bin", "cli.js");
  run("node", [cliPath, schemaJsonPath, "-o", outputFile]);

  const header = [
    "// 이 파일은 생성됩니다 — 손으로 고치지 마세요.",
    "// `pnpm --dir frontend generate:api` 로 backend/config/api.py 의 OpenAPI 스키마에서",
    "// 다시 만듭니다 — 산출물은 packages/bff-client 가 소유하고 두 앱이 함께 씁니다(#146).",
    "// 다시 만듭니다. CI가 이 파일이 최신인지 확인합니다(재생성 후 diff가 나면 실패).",
    "",
  ].join("\n");

  const generated = readFileSync(outputFile, "utf-8");
  writeFileSync(outputFile, header + generated);
  console.log(`written: ${path.relative(packageRoot, outputFile)}`);
} finally {
  rmSync(tmpDir, { recursive: true, force: true });
}
