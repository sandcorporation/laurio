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
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

import { runSeed } from "./lib/seed-http";

const RUN_ID_FILE = path.resolve(__dirname, "../.e2e-run-id");
// 이 파일은 frontend/e2e/에 있다 — e2e/lib/seed-operator.ts(frontend/e2e/lib/)
// 보다 한 단계 얕다. 그쪽의 "../../../backend"를 그대로 복사했다가 저장소
// 밖(워크트리 상위)을 가리켜 `spawnSync uv ENOENT`로 표면화된 적이 있다 — 실제
// 원인은 PATH가 아니라 잘못된 cwd였다. 디렉터리 깊이가 다르면 상대 경로도
// 다시 계산해야 한다.


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
    `${publicBase}/dev-tokens`,
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
  const pruneOtherRuns = (await runSeed("operator-queues", {
    run_id: runId,
    prune_other_runs: true,
  })) as { pruned: number };
  // eslint-disable-next-line no-console -- globalSetup은 CI 로그에서 눈에 보여야
  // 실제로 뭔가를 정리했는지 확인할 수 있다.
  console.log(`[global-setup] e2e run id ${runId} — 이전 실행 ${pruneOtherRuns.pruned}건 정리`);

  // **워커별 정리가 걷지 못하는 것을 여기서 한 번 걷는다** (#104).
  // `seed_e2e_contests` 는 이제 자기 네임스페이스만 지운다 — 그래야 옆 워커를
  // 파괴하지 않는다. 그 대가로 죽은 워커가 남긴 네임스페이스와, 런타임에
  // Contest 를 만드는 스펙들이 쓰는 `[E2E] ` 접두어를 아무도 안 걷는다.
  // 접두어가 없던 시절 그것들이 쌓여 목록 페이지네이션 스펙이 조용히 깨졌다.
  //
  // 여기는 워커가 아직 하나도 없는 시점이라 경합이 성립하지 않는다.
  const prunedAll = (await runSeed("contests", { prune_all_namespaces: true })) as {
    output?: string;
  };
  // eslint-disable-next-line no-console -- 위와 같은 이유.
  console.log(`[global-setup] ${prunedAll.output ?? "pruned"}`);

  // **Contest 만 걷혔고 기준데이터와 정책은 안 걷혔다** (#183). 위 두 정리는 제목
  // 접두어로 Contest 를 가르는데, 같은 e2e 가 만드는 Category·DeliverableType 과
  // 정책 단일 행에는 그 관용구가 적용된 적이 없다. 그래서 dev 스택에서 산출물
  // 종류가 132개(진짜는 5개)까지 쌓여 개최 화면의 요구형태 체크박스 목록이 통째로
  // 묻혔고, 플랫폼 수수료율은 e2e 가 남긴 324bps 였다 — 화면에 보이는 실수령액이
  // 실제 정책과 다르다는 뜻이라, 눈으로 확인하는 개발 방식 자체가 무뎌진다.
  //
  // 여기에 두는 이유는 위 둘과 같다: 워커가 아직 하나도 없어 경합이 성립하지 않고,
  // 어떤 프로젝트의 첫 테스트보다도 먼저 끝난다.
  // **이 정리만은 실패해도 스위트를 세우지 않는다.** 위 둘은 테스트의 정확성을
  // 떠받치지만(이전 실행이 남긴 Contest 가 목록 스펙을 깨뜨린다) 이것은 dev 화면의
  // 가독성을 위한 것이라 없어도 테스트는 옳다. 그런데 여기서 던지면 `globalSetup`
  // 이 죽어 **102건이 한 건도 못 돈다** — 그리고 그 실패는 가장 그럴듯한 원인이
  // 하필 무관한 것이다: CLAUDE.md 대로 `frontend` 컨테이너는 바깥 체크아웃을 서빙
  // 하는데 백엔드가 이 등록부 항목을 아직 모르면 404 가 나고, 그러면 「청소가 아직
  // 없다」가 「e2e 전부 실패」로 보인다.
  try {
    const prunedJunk = (await runSeed("prune-junk", {})) as {
      categories_deleted: number;
      deliverable_types_deleted: number;
      skipped: string[];
      policy_reset: Record<string, [number, number]>;
    };
    const skipped = prunedJunk.skipped ?? [];
    const policyFields = Object.keys(prunedJunk.policy_reset ?? {});
    // eslint-disable-next-line no-console -- 위와 같은 이유. 건너뛴 것이 있으면 그것도
    // 보여야 한다 — 청소가 조용히 아무것도 못 한 것과 할 일이 없던 것은 다르다.
    console.log(
      `[global-setup] e2e 기준데이터 정리 — 카테고리 ${prunedJunk.categories_deleted}건, ` +
        `산출물 종류 ${prunedJunk.deliverable_types_deleted}건 삭제` +
        (skipped.length ? `, 참조가 걸려 건너뜀: ${skipped.join(", ")}` : "") +
        (policyFields.length ? `, 정책 ${policyFields.length}개 필드를 기준값으로 되돌림` : ""),
    );
  } catch (cause) {
    // eslint-disable-next-line no-console -- 조용히 넘어가지는 않는다. 화면이 다시
    // 잡데이터로 덮이기 시작하면 이 줄이 그 이유를 말해 준다.
    console.warn(`[global-setup] e2e 기준데이터 정리를 건너뛴다: ${String(cause)}`);
  }

  // **호출을 잊고 있었다.** 이 함수는 진작 있었고 CLAUDE.md 는 워밍업이 돌고
  // 있다고 적어 뒀는데, 정의만 되고 불리지 않았다 — 즉 기록된 "웜 2.5분" 이
  // 아니라 계속 "콜드 5.6분" 을 내고 있었다. 코드리뷰가 잡았다.
  await warmRoutes();
}
