import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import {
  E2E_OPERATOR_PASSWORD,
  clearE2eOperatorQueues,
  seedE2eOperator,
  seedE2eOperatorQueues,
} from "../lib/seed-operator";
import { establishOperatorSession } from "../lib/session";

// 운영자 앱 10(#68) — 지급 큐: 확정 후 막혀 있는 Payout이 "무엇에" 막혀 있는지
// 보여준다(ADR-0008/0020). ADR-0020이 CONFIRMED_IDENTITY_PENDING과
// CONFIRMED_SELLER_PENDING을 하나로 뭉치지 않은 것은 운영자가 이 화면에서 그
// 구별을 실제로 볼 수 있다는 전제 위에 서 있었다 — 이 스펙이 그 전제를 검증한다.
//
// 시임 규약(ADR-0021)을 그대로 따른다. seed_e2e_operator_queues는 멱등하지
// 않으므로(seed-operator.ts 상단 주석), 절대값이 아니라 "이 테스트가 심은
// idempotency_key가 보이는가/안 보이는가"나 "부르기 전 대비 증분"으로만 단언한다.

async function loginAsOperator(page: Page, username: string): Promise<void> {
  await establishOperatorSession(page, username, E2E_OPERATOR_PASSWORD);
  await expect(page.getByTestId("operator-home-heading")).toBeVisible();
}

/** 큐 카드 하나의 현재 표시값을 읽는다 — home.spec.ts와 같은 관용구. */
async function readHomeQueueValue(page: Page, testId: string): Promise<number> {
  const countLocator = page.getByTestId(`${testId}-count`);
  const emptyLocator = page.getByTestId(`${testId}-empty`);
  await expect(countLocator.or(emptyLocator)).toBeVisible();

  if ((await emptyLocator.count()) > 0) return 0;
  const text = await countLocator.textContent();
  return Number.parseInt(text ?? "0", 10);
}

/** 목록이 로딩을 끝내고 정착할 때까지 기다린다 — locator.all()/count()는
 * 자동 대기하지 않는다는 트랩(이 저장소가 실제로 겪었다)을 피하려고, "로딩이
 * 없다"를 확인하는 대신 list·empty·error 셋 중 하나가 실제로 화면에 뜨는 것을
 * 기다린다("로딩이 아직 안 나타난 순간"에 통과해버리는 거짓 성공을 막는다). */
async function waitForQueueSettled(page: Page): Promise<void> {
  const settled = page
    .getByTestId("payout-queue-list")
    .or(page.getByTestId("payout-queue-empty"))
    .or(page.getByTestId("payout-queue-error"));
  await expect(settled).toBeVisible();
}

test.describe("지급 큐 — 무엇에 막혀 있는가(#68, ADR-0020)", () => {
  test("확정 후 막혀 있는 Payout이 콘테스트·개발자·금액·막힌 이유와 함께 보인다", async ({
    page,
  }) => {
    const operator = await seedE2eOperator();
    const seeded = await seedE2eOperatorQueues("identity");
    const identityPayout = seeded.identity_pending_payout;
    if (!identityPayout) throw new Error("identity_pending_payout 시드가 비어 있다");

    await loginAsOperator(page, operator.username);
    await page.goto("/payouts?blocked_on=identity");
    await waitForQueueSettled(page);

    const row = page.getByTestId(`payout-row-${identityPayout.idempotency_key}`);
    await expect(row).toBeVisible();
    await expect(row.getByTestId("payout-row-contest")).toContainText(String(identityPayout.contest_id));
    await expect(row.getByTestId("payout-row-developer")).toBeVisible();
    await expect(row.getByTestId("payout-row-amount")).toBeVisible();
    await expect(row.getByTestId("payout-blocked-badge-identity")).toBeVisible();
  });

});

// --- #91: 세 번째 배지가 스타일 없이 그려진다 ------------------------------------
//
// `PayoutBadge` 는 `badge-waiting-${blockedOn}` 을 조립하는데(operator/app/payouts/
// page.tsx) `operator/app/globals.css` 에는 identity·seller 둘만 정의돼 있었다 —
// transfer 행은 세 번째 종류인데 배경도 테두리도 없이 본문 텍스트로 그려진다.
// 기존 배지 테스트는 `class` 문자열만 비교해서(문자열은 실제로 다르다) 이걸
// 잡지 못했다. **실제로 칠해졌는가**를 본다.
//
// 실이체 대기(#57 코드리뷰 2차 지적 1)를 만드는 시드가 없으므로 응답을 갈아끼운다 —
// 확인 대상이 백엔드 판정이 아니라 이 화면의 스타일이기 때문이다.
test.describe("지급 큐 — 세 번째 배지도 배지로 그려진다(#91)", () => {
  const TRANSFER_ROW = {
    idempotency_key: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    contest_id: 4242,
    developer_user_id: 77,
    net_amount: 856_000,
    status: "confirmed_seller_pending",
    transfer_status: "failed",
    blocked_on: "transfer",
    seller_status: "partially_approved",
    has_identity: true,
    created_at: new Date().toISOString(),
  };

});

// --- #149: 좁히기·자르기는 백엔드가 한다 ------------------------------------------
//
// 예전에는 이 화면이 「전체」에서 엔드포인트 셋을 병렬로 부른 뒤 응답을 이어 붙이고
// **브라우저에서 정렬**했고, 홈은 배지 숫자 셋을 얻으려고 그 목록 셋을 통째로 받아
// `.length` 를 셌다. 목록에 페이지네이션이 붙는 순간 그 둘은 조용히 틀린다 — 세
// 목록의 1페이지를 합친 것은 합집합의 1페이지가 아니고, 첫 페이지의 길이는 전체
// 건수가 아니다.
test.describe("지급 큐 — 좁히기와 자르기는 백엔드가 한다(#149)", () => {
  function countQueueRequests(page: Page): { urls: string[] } {
    const urls: string[] = [];
    page.on("request", (request) => {
      const url = request.url();
      if (url.includes("/api/backend/operator/payouts")) urls.push(url);
    });
    return { urls };
  }

});
