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

export type SeedOperatorOptions = {
  username?: string;
  password?: string;
  superuser?: boolean;
};

/** `seed_e2e_operator` 관리 명령을 돌려 로그인 가능한 Operator 계정을 멱등하게
 * 만든다(backend/accounts/management/commands/seed_e2e_operator.py). */
export function seedE2eOperator(options: SeedOperatorOptions = {}): SeededOperator {
  const args = ["run", "python", "manage.py", "seed_e2e_operator"];
  if (options.username) args.push("--username", options.username);
  args.push("--password", options.password ?? E2E_OPERATOR_PASSWORD);
  if (options.superuser) args.push("--superuser");

  const output = execFileSync("uv", args, {
    cwd: BACKEND_DIR,
    env: { ...process.env, LAURIO_DB_PORT: backendDbPort() },
    encoding: "utf-8",
    stdio: ["ignore", "pipe", "inherit"],
  });

  const lines = output.trim().split("\n");
  const lastLine = lines[lines.length - 1] ?? "";

  let parsed: unknown;
  try {
    parsed = JSON.parse(lastLine);
  } catch {
    throw new Error(
      "seed_e2e_operator 가 JSON 을 내지 않았다 — 명령이 죽었을 가능성이 크다" +
        ` (stderr 는 위에 그대로 찍힌다). 마지막 줄: ${JSON.stringify(lastLine.slice(0, 300))}`,
    );
  }

  const seeded = parsed as SeededOperator;
  if (!seeded?.id || !seeded?.username) {
    throw new Error(
      `seed_e2e_operator 의 출력에 기대한 키가 없다: ${JSON.stringify(Object.keys(seeded ?? {}))}`,
    );
  }
  return seeded;
}
