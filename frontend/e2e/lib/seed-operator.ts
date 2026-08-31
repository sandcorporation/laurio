// 운영자 앱 e2e 전용 시드(#63). `e2e/lib/seed.ts`(공개 앱 콘테스트 시드)와 같은
// 관용구를 따르되 별도 파일로 둔다 — 두 시드는 서로 다른 도메인을 건드리고,
// 독립적인 체인들이 같은 파일을 동시에 고칠 필요가 없게 한다.
import { execFileSync } from "node:child_process";
import path from "node:path";

const BACKEND_DIR = path.resolve(__dirname, "../../../backend");

export type SeededOperator = {
  id: number;
  username: string;
  is_superuser: boolean;
};

export const E2E_OPERATOR_PASSWORD = "e2e-operator-pw-9134-xyz";

function backendDbPort(): string {
  return process.env.LAURIO_DB_PORT ?? "55432";
}

/** `manage.py <command> <args>`를 돌리고 마지막 줄의 JSON을 파싱한다 —
 * seed_e2e_operator*.py 관리 명령들이 공통으로 쓰는 관용구
 * (frontend/e2e/lib/seed.ts의 seedE2eContests와 같은 이유: uv run이 남기는
 * 진행 로그가 stdout 앞에 섞일 수 있어 마지막 줄만 파싱한다). */
function runSeedCommand(command: string, args: string[]): unknown {
  const output = execFileSync("uv", ["run", "python", "manage.py", command, ...args], {
    cwd: BACKEND_DIR,
    env: { ...process.env, LAURIO_DB_PORT: backendDbPort() },
    encoding: "utf-8",
    stdio: ["ignore", "pipe", "inherit"],
  });

  const lines = output.trim().split("\n");
  const lastLine = lines[lines.length - 1] ?? "";

  try {
    return JSON.parse(lastLine);
  } catch {
    throw new Error(
      `${command} 가 JSON 을 내지 않았다 — 명령이 죽었을 가능성이 크다` +
        ` (stderr 는 위에 그대로 찍힌다). 마지막 줄: ${JSON.stringify(lastLine.slice(0, 300))}`,
    );
  }
}

export type SeedOperatorOptions = {
  username?: string;
  password?: string;
  superuser?: boolean;
};

/** `seed_e2e_operator` 관리 명령을 돌려 로그인 가능한 Operator 계정을 멱등하게
 * 만든다(backend/accounts/management/commands/seed_e2e_operator.py). */
export function seedE2eOperator(options: SeedOperatorOptions = {}): SeededOperator {
  const args: string[] = [];
  if (options.username) args.push("--username", options.username);
  args.push("--password", options.password ?? E2E_OPERATOR_PASSWORD);
  if (options.superuser) args.push("--superuser");

  const seeded = runSeedCommand("seed_e2e_operator", args) as SeededOperator;
  if (!seeded?.id || !seeded?.username) {
    throw new Error(
      `seed_e2e_operator 의 출력에 기대한 키가 없다: ${JSON.stringify(Object.keys(seeded ?? {}))}`,
    );
  }
  return seeded;
}

export type SeededOperatorQueues = {
  appeal?: { appeal_id: number; contest_id: number };
  identity_pending_payout?: { idempotency_key: string; contest_id: number };
  seller_pending_payout?: { idempotency_key: string; contest_id: number };
};

/** `seed_e2e_operator_queues` 관리 명령을 돌려 「할 일」 세 큐에 한 건씩 심는다
 * (backend/accounts/management/commands/seed_e2e_operator_queues.py). **멱등하지
 * 않다** — 부를 때마다 새 데이터가 쌓인다. 그래서 호출부는 항상 부르기 전
 * baseline 대비 증분으로 검증해야 한다. `only`를 주면 그 큐 하나만 심는다. */
export function seedE2eOperatorQueues(only?: "appeal" | "identity" | "seller"): SeededOperatorQueues {
  const args = only ? ["--only", only] : [];
  return runSeedCommand("seed_e2e_operator_queues", args) as SeededOperatorQueues;
}

/** 세 큐를 전부 빈 상태로 되돌린다("0건은 0건이라고 말한다"는 인수조건을 실제
 * 0 상태에서 확인하기 위한 것) — 이 체인의 compose 스택 전용 DB에서만 안전하다. */
export function clearE2eOperatorQueues(): { appeals_deleted: number; payouts_deleted: number } {
  return runSeedCommand("seed_e2e_operator_queues", ["--clear"]) as {
    appeals_deleted: number;
    payouts_deleted: number;
  };
}
