// Playwright globalSetup — 전체 스위트에서 딱 한 번, 어떤 프로젝트의 워커도
// 뜨기 전에 메인 프로세스에서 실행된다(playwright.config.ts가 등록한다).
//
// 운영자 큐 시드가 "이번 실행이 만든 것"과 "이전 실행이 남긴 것"을 구별하는 데
// 쓸 토큰을 여기서 새로 발급한다 — e2e/lib/run-id.ts 상단 주석 참고. 매 실행마다
// 무조건 새로 쓴다(이전 실행이 남긴 파일이 있어도 덮어쓴다) — 그래야 "이번
// 실행"의 경계가 항상 이 프로세스의 시작 시점과 일치한다.
//
// **그리고 여기서 곧바로 이전 실행의 own-prefix Contest를 정리한다**(#70
// 코드리뷰가 실제로 재현한 회귀). `playwright.config.ts`는 `public` 프로젝트를
// `operator` 프로젝트보다 먼저 나열하고, 워커가 하나뿐이라(workers: 1) 실행
// 순서도 그대로 따른다 — 즉 `public` 프로젝트의 `contests-list.spec.ts`가 항상
// 먼저 돈다. 정리를 `seed_e2e_operator_queues`의 첫 호출(=operator 프로젝트의
// 첫 테스트)까지 미루면, 그보다 먼저 도는 public 목록 e2e가 **이전 실행이 남긴
// Contest를 이미 관찰해 버린 뒤**라 아무 소용이 없다 — 실제로 이 순서 문제
// 때문에 "실행 토큰으로 가른다"는 백엔드 수정만으로는 깨끗한 스택에서 연달아
// 두 번 돌리는 시나리오가 여전히 깨졌다. 그래서 어떤 프로젝트의 테스트가
// 실행되기도 전에, 이 파일에서 직접 정리를 먼저 끝낸다.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

const RUN_ID_FILE = path.resolve(__dirname, "../.e2e-run-id");
// 이 파일은 frontend/e2e/에 있다 — e2e/lib/seed-operator.ts(frontend/e2e/lib/)
// 보다 한 단계 얕다. 그쪽의 "../../../backend"를 그대로 복사했다가 저장소
// 밖(워크트리 상위)을 가리켜 `spawnSync uv ENOENT`로 표면화된 적이 있다 — 실제
// 원인은 PATH가 아니라 잘못된 cwd였다. 디렉터리 깊이가 다르면 상대 경로도
// 다시 계산해야 한다.
const BACKEND_DIR = path.resolve(__dirname, "../../backend");

function backendDbPort(): string {
  return process.env.LAURIO_DB_PORT ?? "55432";
}

// Next dev 서버는 라우트를 **요청받을 때** 컴파일한다. 그래서 스위트의 첫
// 실행은 테스트가 아니라 컴파일을 기다린다 — 실측으로 public 프로젝트가 콜드
// 5.6분, 웜 2.5분이었다(같은 79건). 그 차이가 통째로 첫 방문 비용이고,
// contests-pagination 은 30초 타임아웃을 먹고 실패하기까지 했다.
//
// 그래서 워커가 뜨기 전에 여기서 주요 라우트를 한 번씩 친다. 응답 내용은 보지
// 않는다 — 컴파일만 시키면 되고, 실패해도(스택이 아직 안 떴거나 그 라우트가
// 인증을 요구하거나) 그냥 넘어간다. 이 함수의 일은 테스트가 아니라 준비다.
async function warmRoutes(): Promise<void> {
  const publicBase = process.env.LAURIO_E2E_BASE_URL ?? "http://127.0.0.1:53000";
  const operatorBase = process.env.LAURIO_OPERATOR_E2E_BASE_URL ?? "http://127.0.0.1:53001";
  const targets = [
    `${publicBase}/`,
    `${publicBase}/contests`,
    `${publicBase}/login`,
    `${publicBase}/console`,
    `${operatorBase}/login`,
    `${operatorBase}/`,
    `${operatorBase}/appeals`,
    `${operatorBase}/payouts`,
    `${operatorBase}/operators`,
    `${operatorBase}/policy`,
    `${operatorBase}/deliverable-types`,
  ];
  const started = Date.now();
  await Promise.all(
    targets.map((url) =>
      fetch(url, { redirect: "manual" }).catch(() => undefined),
    ),
  );
  // eslint-disable-next-line no-console -- 워밍업이 실제로 돌았는지 CI 로그에서 보여야 한다.
  console.log(`[global-setup] warmed ${targets.length} routes in ${Date.now() - started}ms`);
}

export default async function globalSetup(): Promise<void> {
  const runId = randomUUID().slice(0, 8);
  fs.writeFileSync(RUN_ID_FILE, runId, "utf-8");

  // seed_e2e_operator_queues.py의 `--prune-other-runs` — 심지 않고, 이 run id가
  // 아닌 own-prefix Contest만 정리한다. `_refuse_in_deployed_environment()`가
  // 배포 환경에서는 이 호출 자체를 거부한다(그 명령의 기존 안전장치 그대로).
  const output = execFileSync(
    "uv",
    ["run", "python", "manage.py", "seed_e2e_operator_queues", "--prune-other-runs"],
    {
      cwd: BACKEND_DIR,
      env: { ...process.env, LAURIO_DB_PORT: backendDbPort(), LAURIO_E2E_RUN_ID: runId },
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "inherit"],
    },
  );
  // eslint-disable-next-line no-console -- globalSetup은 CI 로그에서 눈에 보여야
  // 실제로 뭔가를 정리했는지 확인할 수 있다.
  console.log(`[global-setup] e2e run id ${runId} — ${output.trim().split("\n").pop()}`);
}
