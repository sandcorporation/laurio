// 운영자 앱 e2e 전용 시드(#63). `e2e/lib/seed.ts`(공개 앱 콘테스트 시드)와 같은
// 관용구를 따르되 별도 파일로 둔다 — 두 시드는 서로 다른 도메인을 건드리고,
// 독립적인 체인들이 같은 파일을 동시에 고칠 필요가 없게 한다.

import { e2eRunId } from "./run-id";

import { runSeed } from "./seed-http";

// **서브프로세스로 도는 시드는 더 이상 없다** (#194). 채점을 거치는 시드 둘만
// `uv run python manage.py` 로 남아 있었는데, 그 이유는 소스를 `FakeStorageAdapter`
// 에 **직접** 쓴 뒤 같은 프로세스에서 채점 스캔을 돌렸기 때문이다 —
// `STORAGE_BACKEND=fake` 인 호스트에서만 성립하는 결합이었다. `write_object` 가
// 어댑터 계약에 들어가면서(#194) 그 시드가 설정된 어댑터를 쓰게 됐고, 컨테이너 안의
// MinIO 로도 자기 완결적이 됐다.
//
// 그 결합 하나가 e2e 러너에 파이썬 툴체인과 **DB 포트 노출**을 남기고 있었다.
// 둘 다 이 파일에서 사라진다.


export type SeededOperator = {
  id: number;
  username: string;
  is_superuser: boolean;
};

export const E2E_OPERATOR_PASSWORD = "e2e-operator-pw-9134-xyz";

/** 등록부의 시드 하나를 HTTP 로 돌린다 (#156).
 *
 * `run_id` 를 매번 명시적으로 실어 보낸다 — 이번 스위트 실행이 심은 Contest 를 이전
 * 실행이 남긴 것과 구별하는 토큰이다(e2e/lib/run-id.ts, seed_e2e_operator_queues.py 의
 * `_own_title_prefix`). 예전에는 환경변수로 넘겼는데, HTTP 로 부르면 **부르는 쪽의
 * 환경변수가 백엔드 프로세스에 있을 리 없다.** 어긋나면 「매 호출이 서로 다른 토큰을 받아
 * 서로의 형제를 지우는」 조용한 사고가 된다. */
async function runSeedCommand(name: string, options: Record<string, unknown> = {}): Promise<unknown> {
  return runSeed(name, options);
}

export type SeedOperatorOptions = {
  username?: string;
  password?: string;
  superuser?: boolean;
};

// 인자 없이 부른 결과를 프로세스 안에서 재사용한다.
//
// **측정해서 넣었다.** 운영자 스펙의 시드 호출 127회 중 79회가 이 함수였고,
// 한 번에 약 1.4초(그중 Django 부팅만 640ms)라 계정을 만드는 데만 95초가
// 쓰였다 — 운영자 스위트 344초의 4분의 1이다. `uv run` 오버헤드는 40ms 라
// 거기서 줄일 것은 없었다(직접 호출 641ms vs uv run 651ms). 줄일 수 있는 건
// 호출당 비용이 아니라 **호출 횟수**다.
//
// **인자를 주면 캐시를 쓰지 않는다.** 계정 자체를 바꾸는 스펙(비활성화·
// 재활성화·등급 확인)은 서로 간섭하면 안 되므로 지금처럼 고유한 이름을 주고,
// 그 호출은 매번 새로 만든다. "로그인할 계정이 하나 필요할 뿐" 인 대다수만
// 공유한다 — 운영자 신원은 그 테스트들이 단언하는 대상이 아니다.
//
// 캐시는 워커 프로세스 하나 안에서만 산다. Playwright 가 워커를 여럿 쓰면
// 워커마다 하나씩 만들어지는데, 이름이 고정이고 명령이 멱등하므로
// (`seed_e2e_operator` 는 get_or_create 다) 그래도 안전하다.
const SHARED_OPERATOR_USERNAME = "e2e-op-shared";
let sharedOperator: SeededOperator | null = null;

/** `seed_e2e_operator` 관리 명령을 돌려 로그인 가능한 Operator 계정을 멱등하게
 * 만든다(backend/accounts/management/commands/seed_e2e_operator.py).
 *
 * 인자 없이 부르면 이 프로세스가 이미 만든 공유 계정을 그대로 돌려준다. 계정을
 * 변경하는 테스트는 반드시 고유한 `username` 을 줘야 한다. */
export async function seedE2eOperator(options: SeedOperatorOptions = {}): Promise<SeededOperator> {
  const wantsShared =
    options.username === undefined && options.password === undefined && !options.superuser;
  if (wantsShared && sharedOperator) return sharedOperator;
  if (wantsShared) {
    sharedOperator = await seedOperatorAccount({ ...options, username: SHARED_OPERATOR_USERNAME });
    return sharedOperator;
  }
  return seedOperatorAccount(options);
}

async function seedOperatorAccount(options: SeedOperatorOptions): Promise<SeededOperator> {
  const seeded = (await runSeedCommand("operator", {
    username: options.username || undefined,
    password: options.password ?? E2E_OPERATOR_PASSWORD,
    superuser: options.superuser || undefined,
  })) as SeededOperator;
  if (!seeded?.id || !seeded?.username) {
    throw new Error(
      `operator 시드의 출력에 기대한 키가 없다: ${JSON.stringify(Object.keys(seeded ?? {}))}`,
    );
  }
  return seeded;
}

export type SeededOperatorQueues = {
  appeal?: {
    appeal_id: number;
    contest_id: number;
    // submission_id·reason·dev_access는 운영자 앱 08(#66)이 덧붙였다 — 옵셔널로
    // 둔 것은 이 타입이 옛 응답 모양(appeal_id·contest_id만)도 여전히 표현할 수
    // 있어야 하기 때문이 아니라, 실제로는 항상 채워진다(백엔드가 additive하게만
    // 바꿨다)는 점을 타입에서까지 강제하지 않기 위해서다.
    submission_id: number;
    reason: string;
    dev_access: string;
  };
  identity_pending_payout?: { idempotency_key: string; contest_id: number };
  seller_pending_payout?: { idempotency_key: string; contest_id: number };
};

/** `seed_e2e_operator_queues` 관리 명령을 돌려 「할 일」 세 큐에 한 건씩 심는다
 * (backend/accounts/management/commands/seed_e2e_operator_queues.py). **멱등하지
 * 않다** — 부를 때마다 새 데이터가 쌓인다. 그래서 호출부는 항상 부르기 전
 * baseline 대비 증분으로 검증해야 한다. `only`를 주면 그 큐 하나만 심는다. */
export async function seedE2eOperatorQueues(
  only?: "appeal" | "identity" | "seller",
): Promise<SeededOperatorQueues> {
  return (await runSeedCommand("operator-queues", {
    run_id: e2eRunId(),
    ...(only ? { only } : {}),
  })) as SeededOperatorQueues;
}

/** 세 큐를 전부 빈 상태로 되돌린다("0건은 0건이라고 말한다"는 인수조건을 실제
 * 0 상태에서 확인하기 위한 것) — 이 체인의 compose 스택 전용 DB에서만 안전하다. */
export async function clearE2eOperatorQueues(): Promise<{
  appeals_deleted: number;
  payouts_deleted: number;
}> {
  return (await runSeedCommand("operator-queues", { run_id: e2eRunId(), clear: true })) as {
    appeals_deleted: number;
    payouts_deleted: number;
  };
}

// backend/appeals/schemas.py의 RulingOut과 필드 이름을 맞춘다 —
// seed_e2e_operator_appeal.py가 이 값을 손으로 재구성하지 않고 상세 조회
// (GET /operator/appeals/{id})의 응답을 그대로 돌려주기 때문이다.
export type SeededAppealRuling = {
  decision: "upheld" | "rejected";
  ruled_by_id: number;
  ruled_by_username: string;
  note: string;
  ruled_at: string;
  correction_amount: number | null;
  correction_journal_entry_id: number | null;
};

export type SeededAppealForDetail = {
  appeal_id: number;
  contest_id: number;
  submission_id: number;
  reason: string;
  // 소스 요청 본문(scoring 프롬프트)에 실제로 심겨 있는 유일한 마커 — 이의
  // 상세를 펼치기 전에는 화면 어디에도 없어야 하고, 펼친 뒤에만 나타나야 한다
  // (#66 AC, ADR-0022).
  source_marker: string;
  // Developer 본인의 JWT — GET /api/submissions/{id}/source-readings(티켓 03)를
  // e2e가 직접 쳐서 "펼침이 실제로 열람 기록을 남겼는가"를 확인하는 데 쓴다.
  dev_access: string;
  status: "pending" | "upheld" | "rejected";
  ruling: SeededAppealRuling | null;
};

/** `seed_e2e_operator_appeal` 관리 명령을 돌려 이의 상세 화면 e2e에 필요한 이의
 * 하나를 심는다(backend/accounts/management/commands/seed_e2e_operator_appeal.py).
 * `rule`을 주면 그 결정으로 즉시 심판까지 마친 이의를 돌려준다 — #66은 심판
 * 폼을 만들지 않지만(#67), 이미 심판된 이의를 필터·읽기 전용 화면으로 보여주는
 * 것은 검증해야 한다. 멱등하지 않다 — 매 호출이 새 Contest·Submission·Appeal을
 * 만든다. */
export async function seedE2eOperatorAppeal(
  rule?: "uphold" | "reject",
): Promise<SeededAppealForDetail> {
  return (await runSeedCommand("operator-appeal", {
    run_id: e2eRunId(),
    ...(rule ? { rule } : {}),
  })) as SeededAppealForDetail;
}

function backendApiPort(): string {
  return process.env.LAURIO_API_PORT ?? "58000";
}

/** Developer 본인의 소스 열람 기록 수를 백엔드에서 직접 센다(`GET
 * /api/submissions/{id}/source-readings`, JWT 인증, 티켓 03) — 운영자 앱의 BFF를
 * 거치지 않고 백엔드 컨테이너의 호스트 노출 포트를 직접 친다. 이 엔드포인트는
 * 운영자 앱이 아니라 공개 앱(Developer)의 표면이라 운영자 BFF의 허용목록에
 * 없고, 있어서도 안 된다(ADR-0021) — 그래서 e2e가 직접 HTTP로 확인한다. */
export async function sourceReadingCount(submissionId: number, devAccess: string): Promise<number> {
  const res = await fetch(
    `http://127.0.0.1:${backendApiPort()}/api/submissions/${submissionId}/source-readings`,
    { headers: { Authorization: `Bearer ${devAccess}` } },
  );
  if (!res.ok) {
    throw new Error(`source-readings 조회 실패: ${res.status} ${await res.text()}`);
  }
  // #72 부터 이 표면은 페이지네이션된다({items, count}) — 열람은 중복 제거가
  // 없어 무제한으로 쌓일 수 있기 때문이다. 여기서 필요한 것은 "몇 번 열렸는가"
  // 이므로 페이지의 길이가 아니라 전체 개수인 count 를 쓴다.
  const body = (await res.json()) as { items: unknown[]; count: number };
  return body.count;
}

/** 한 Contest의 원장 분개 개수를 `count_ledger_entries` 관리 명령으로 직접
 * 원장에서 센다(#67). 재심판 시도가 409로 거절되는 것으로 멈추지 않고, 그
 * 거절이 실제로 정정 분개를 하나도 더 만들지 않았음을 확인하는 데 쓴다 —
 * 원장은 append-only라 잘못 남은 정정은 지울 수 없다. */
export async function ledgerEntryCount(contestId: number): Promise<number> {
  const result = (await runSeedCommand("ledger-entry-count", { contest_id: contestId })) as {
    count: number;
  };
  return result.count;
}
