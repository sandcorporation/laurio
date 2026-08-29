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
  is_underfunded: boolean;
  required_minimum_prize: number;
  deliverable_types: string[];
  requirements: SeededRequirement[];
};

export type SeededContests = {
  funded: SeededContest;
  underfunded: SeededContest;
  closed: SeededContest;
  draft: SeededContest;
};

// dev compose 의 기본값(docker/compose.dev.yaml, config/settings.py)과 같다 —
// 이 체인이 포트를 비켜 잡았다면(디스패치 지침) 테스트 실행 전에
// `LAURIO_DB_PORT` 를 그 값으로 export 해야 한다.
function backendDbPort(): string {
  return process.env.LAURIO_DB_PORT ?? "55432";
}

export function seedE2eContests(): SeededContests {
  const output = execFileSync("uv", ["run", "python", "manage.py", "seed_e2e_contests"], {
    cwd: BACKEND_DIR,
    env: { ...process.env, LAURIO_DB_PORT: backendDbPort() },
    encoding: "utf-8",
    stdio: ["ignore", "pipe", "inherit"],
  });

  // 명령은 마지막 줄에 JSON 한 덩어리만 찍는다(관리 명령 docstring 참고) —
  // 그래도 `uv run` 이 최초 실행 시 남기는 진행 로그(가상환경 생성 등)가 stdout
  // 앞에 섞일 수 있어, 마지막 줄만 파싱한다.
  const lines = output.trim().split("\n");
  const lastLine = lines[lines.length - 1];
  return JSON.parse(lastLine) as SeededContests;
}
