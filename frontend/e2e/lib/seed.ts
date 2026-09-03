// FE-04/FE-05(#29·#30) SSR 테스트가 검증할 **백엔드가 준 값**을 만든다
// (frontend/e2e/seam.spec.ts 상단 주석 — "실제로 갈리는 것은 백엔드에서 온
// 데이터다"). 하드코딩한 프론트 픽스처를 쓰면 그 구분이 사라지므로, 실제
// Django DB에 진짜 Contest 를 심는다.
//
// `backend/contests/management/commands/seed_e2e_contests.py` 를 호스트에서
// `uv run manage.py` 로 직접 돌린다 — `docker compose exec` 를 쓰지 않는 이유는
// compose 프로젝트 이름(`-p`)이 실행 환경마다 다르기 때문이다(디스패치 지침의
// 체인 전용 포트처럼, 로컬은 `laurio-ch-c`, CI는 compose 파일의 기본
// `laurio-dev`) — 이름을 잘못 짚으면 엉뚱한(또는 无관한) 스택의 backend
// 컨테이너를 건드릴 위험이 생긴다. 반면 dev DB는 항상 호스트에 포트로
// 노출되어 있고(docker/compose.dev.yaml, LAURIO_DB_PORT) `cd backend && uv run
// pytest` 가 이미 이 경로로 같은 DB에 붙는 것이 이 저장소의 기존 관례다
// (CLAUDE.md) — manage.py 커맨드도 같은 경로로 같은 DB에 붙으면 프로젝트
// 이름과 완전히 무관해진다.
import { execFileSync } from "node:child_process";
import path from "node:path";

// playwright 는 이 저장소에서 CommonJS 로 스펙을 트랜스파일한다(package.json 에
// "type": "module" 이 없다) — 그래서 `import.meta.url` 대신 CJS 전역인
// `__dirname` 을 그대로 쓴다.
const BACKEND_DIR = path.resolve(__dirname, "../../../backend");

export type SeededRequirement = { text: string; grade: "required" | "optional" };

export type SeededContest = {
  id: number;
  title: string;
  prize: number;
  deadline_at: string;
  status: "draft" | "published" | "closed" | "awarded" | "judging_ended";
  category: string;
  category_id: number;
  is_underfunded: boolean;
  required_minimum_prize: number;
  deliverable_types: string[];
  deliverable_type_ids: number[];
  requirements: SeededRequirement[];
};

// FE-06(#31) — 개발자 공개 프로필 SSR 테스트가 검증할 백엔드 값. 마감된
// `closed` Contest 에 낸 Submission 하나를 아카이브 항목으로 심는다
// (seed_e2e_contests.py 참고). `sensitive_*` 두 필드는 "존재"가 아니라
// "부재"를 확인하는 용도다 — 이 정확한 문자열이 프로필 페이지의 HTML 응답
// 본문 전체(SSR 페이로드·하이드레이션 스크립트 포함) 어디에도 없어야 한다.
export type SeededDeveloper = {
  id: number;
  display_name: string;
  bio: string;
  archived_submission: {
    contest_id: number;
    contest_title: string;
    demo_url: string;
  };
  sensitive_source_object_key: string;
  sensitive_test_account: string;
};

// FE-11(#36) — 심사 비교 화면(Requirement 축 매트릭스 + Award) 테스트가 쓰는
// 백엔드 값. `sponsor_login_seed`로 fake 로그인하면 이 Contest의 진짜 Sponsor로
// 귀결된다(seed_e2e_contests.py의 _seed_judging_sponsor 참고) — "본인만 Award할
// 수 있다"를 검증하려면 진짜 Sponsor로 로그인해야 하기 때문이다. `sensitive_*`
// 넷은 developer-profile.spec.ts와 같은 원칙 — "부재"를 확인하는 용도이고, 이
// 정확한 문자열이 심사 비교 화면의 HTML 응답 본문(SSR 페이로드·하이드레이션
// 스크립트 포함) 어디에도 없어야 한다.
export type SeededJudgingRequirement = SeededRequirement & { id: number };

export type SeededJudgingContest = {
  id: number;
  title: string;
  sponsor_login_seed: string;
  // 제출이 있는 Developer 로 로그인할 수 있게 하는 seed(#74) — 「내 참가 현황」
  // 처럼 Developer 본인의 화면이 이걸 쓴다.
  developer_login_seed: string;
  judging_ends_at: string;
  requirements: SeededJudgingRequirement[];
  submissions: { id: number; developer_id: number; developer_display_name: string }[];
  sensitive_source_object_key_a: string;
  sensitive_source_object_key_b: string;
  sensitive_test_account: string;
  sensitive_score_model_version: string;
};

// #39 — 목록이 한 페이지를 넘었을 때도 필터·정렬이 정확한지 재현하기 위한 대량
// 시드. `seedE2eContests({ bulk: N })` 로 요청했을 때만 채워진다.
export type SeededBulk = {
  category: string;
  category_id: number;
  count: number;
  /** 상금순 정렬의 첫 항목. */
  highest_prize_title: string;
  /** 상금순 정렬의 마지막 항목 — 예전 구조에서 조용히 사라지던 자리다. */
  lowest_prize_title: string;
};

export type SeededContests = {
  funded: SeededContest;
  underfunded: SeededContest;
  closed: SeededContest;
  draft: SeededContest;
  developer: SeededDeveloper;
  judging: SeededJudgingContest;
  bulk?: SeededBulk;
};

// dev compose 의 기본값(docker/compose.dev.yaml, config/settings.py)과 같다 —
// 이 체인이 포트를 비켜 잡았다면(디스패치 지침) 테스트 실행 전에
// `LAURIO_DB_PORT` 를 그 값으로 export 해야 한다.
function backendDbPort(): string {
  return process.env.LAURIO_DB_PORT ?? "55432";
}

export type SeedOptions = {
  /** 전용 Category 에 공개 Contest 를 이만큼 더 심는다(#39). 느리므로 필요한 스펙에서만 쓴다. */
  bulk?: number;
};

/**
 * 이 워커가 자기 것으로 삼을 네임스페이스 토큰 (#104).
 *
 * **시드는 심기 전에 지운다** — 접두어가 붙은 Contest·계정을 전부 삭제하고 다시
 * 만든다. 워커가 여럿이면 그 삭제가 다른 워커의 픽스처까지 지워서, 실패가 코드
 * 회귀와 구분되지 않는다(예전 병렬화 시도가 16건 실패로 끝난 이유). 워커마다
 * 다른 토큰을 주면 각자 자기 범위만 지운다.
 *
 * `parallelIndex` 는 **동시에 살아 있는 워커 사이에서만** 유일하다(워커가 죽고
 * 새로 뜨면 재사용된다) — 그거면 충분하다. 우리가 막아야 하는 것은 "같은 순간에
 * 도는 두 워커의 충돌"이고, 순차적으로 같은 인덱스를 물려받은 워커는 앞 워커가
 * 이미 끝난 뒤라 지울 것이 자기 것뿐이다.
 *
 * 테스트 밖(예: globalSetup)에서 부르면 인덱스가 없다 — 그때는 네임스페이스
 * 없이, 즉 예전과 같은 `[E2E] ` 로 심는다.
 */
function workerNamespace(): string {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports -- 이 모듈은
    // globalSetup(테스트 밖)에서도 임포트되므로 최상단에서 test 를 끌어오면
    // 그쪽에서 터진다. 실제로 워커 안일 때만 읽는다.
    const { test } = require("@playwright/test") as typeof import("@playwright/test");
    // **같은 머신에서 스위트를 둘 이상 동시에 돌린다면 `LAURIO_E2E_NAMESPACE` 를
    // 서로 다르게 줘라** — `parallelIndex` 는 한 실행 안에서만 유일해서, 두 실행이
    // 각자 `w0` 을 써 서로의 픽스처를 지운다. 병렬 워크트리에서 체인 둘이 각자
    // e2e 를 돌리는 상황이 정확히 그것이다(`LAURIO_TEST_DB_NAME` 을 달리 주는
    // 것과 같은 이유). 명령 쪽 검증이 소문자 영숫자만 받으므로 그 형태로 준다.
    const scope = (process.env.LAURIO_E2E_NAMESPACE ?? "").replace(/[^a-z0-9]/g, "");
    return `${scope}w${test.info().parallelIndex}`;
  } catch {
    return "";
  }
}

export function seedE2eContests(options: SeedOptions = {}): SeededContests {
  const args = ["run", "python", "manage.py", "seed_e2e_contests"];
  const namespace = workerNamespace();
  if (namespace) args.push("--namespace", namespace);
  if (options.bulk) args.push("--bulk", String(options.bulk));

  const output = execFileSync("uv", args, {
    cwd: BACKEND_DIR,
    env: { ...process.env, LAURIO_DB_PORT: backendDbPort() },
    encoding: "utf-8",
    stdio: ["ignore", "pipe", "inherit"],
  });

  // 명령은 마지막 줄에 JSON 한 덩어리만 찍는다(관리 명령 docstring 참고) —
  // 그래도 `uv run` 이 최초 실행 시 남기는 진행 로그(가상환경 생성 등)가 stdout
  // 앞에 섞일 수 있어, 마지막 줄만 파싱한다.
  const lines = output.trim().split("\n");
  const lastLine = lines[lines.length - 1] ?? "";

  // 조용히 실패하지 않게 막는다. 시드 명령이 깨지면 반환값이 뭔가 이상해지고,
  // 그 상태로 스펙이 계속 돌면 진짜 이유(시드가 죽었다)가 아니라 증상(모르는
  // id 로 404)만 보여 진단이 멀어진다 — 실제로 Category 삭제가 ProtectedError
  // 로 죽었을 때 그렇게 헤맸다.
  let parsed: unknown;
  try {
    parsed = JSON.parse(lastLine);
  } catch {
    throw new Error(
      "seed_e2e_contests 가 JSON 을 내지 않았다 — 명령이 죽었을 가능성이 크다" +
        ` (stderr 는 위에 그대로 찍힌다). 마지막 줄: ${JSON.stringify(lastLine.slice(0, 300))}`,
    );
  }

  const seeded = parsed as SeededContests;
  if (!seeded?.funded?.id || !seeded?.judging?.id || !seeded?.developer?.id) {
    throw new Error(
      `seed_e2e_contests 의 출력에 기대한 키가 없다: ${JSON.stringify(Object.keys(seeded ?? {}))}`,
    );
  }
  return seeded;
}
