import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import {
  E2E_OPERATOR_PASSWORD,
  clearE2eOperatorQueues,
  seedE2eOperator,
  seedE2eOperatorQueues,
} from "../lib/seed-operator";

// 운영자 앱 10(#68) — 지급 큐: 확정 후 막혀 있는 Payout이 "무엇에" 막혀 있는지
// 보여준다(ADR-0008/0020). ADR-0020이 CONFIRMED_IDENTITY_PENDING과
// CONFIRMED_SELLER_PENDING을 하나로 뭉치지 않은 것은 운영자가 이 화면에서 그
// 구별을 실제로 볼 수 있다는 전제 위에 서 있었다 — 이 스펙이 그 전제를 검증한다.
//
// 시임 규약(ADR-0021)을 그대로 따른다. seed_e2e_operator_queues는 멱등하지
// 않으므로(seed-operator.ts 상단 주석), 절대값이 아니라 "이 테스트가 심은
// idempotency_key가 보이는가/안 보이는가"나 "부르기 전 대비 증분"으로만 단언한다.

async function loginAsOperator(page: Page, username: string): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("login-username").fill(username);
  await page.getByTestId("login-password").fill(E2E_OPERATOR_PASSWORD);
  await page.getByTestId("login-submit").click();
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
    const operator = seedE2eOperator({ username: `e2e-op-payoutrow-${Date.now()}` });
    const seeded = seedE2eOperatorQueues("identity");
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

  test("필터가 실제로 배제한다 — identity로 걸러도 seller 행은 보이지 않는다(그 반대도)", async ({
    page,
  }) => {
    const operator = seedE2eOperator({ username: `e2e-op-payoutfilter-${Date.now()}` });
    const seeded = seedE2eOperatorQueues();
    const identityPayout = seeded.identity_pending_payout;
    const sellerPayout = seeded.seller_pending_payout;
    if (!identityPayout || !sellerPayout) {
      throw new Error("identity/seller 시드가 비어 있다");
    }

    await loginAsOperator(page, operator.username);

    // identity 필터 — identity 행은 있고 seller 행은 없다(포함만 확인하는 것으로는
    // 깨진 필터를 못 잡는다는 트랩을 피한다).
    await page.goto("/payouts?blocked_on=identity");
    await waitForQueueSettled(page);
    await expect(page.getByTestId(`payout-row-${identityPayout.idempotency_key}`)).toBeVisible();
    await expect(page.getByTestId(`payout-row-${sellerPayout.idempotency_key}`)).toHaveCount(0);

    // seller 필터 — 반대.
    await page.goto("/payouts?blocked_on=seller");
    await waitForQueueSettled(page);
    await expect(page.getByTestId(`payout-row-${sellerPayout.idempotency_key}`)).toBeVisible();
    await expect(page.getByTestId(`payout-row-${identityPayout.idempotency_key}`)).toHaveCount(0);

    // 전체 — 둘 다 있다.
    await page.goto("/payouts");
    await waitForQueueSettled(page);
    await expect(page.getByTestId(`payout-row-${identityPayout.idempotency_key}`)).toBeVisible();
    await expect(page.getByTestId(`payout-row-${sellerPayout.idempotency_key}`)).toBeVisible();
  });

  test("필터 탭을 클릭해도 같은 결과가 된다 — URL이 바뀌고 목록이 갱신된다", async ({ page }) => {
    const operator = seedE2eOperator({ username: `e2e-op-payouttabs-${Date.now()}` });
    const seeded = seedE2eOperatorQueues();
    const identityPayout = seeded.identity_pending_payout;
    const sellerPayout = seeded.seller_pending_payout;
    if (!identityPayout || !sellerPayout) {
      throw new Error("identity/seller 시드가 비어 있다");
    }

    await loginAsOperator(page, operator.username);
    await page.goto("/payouts");
    await waitForQueueSettled(page);

    await page.getByTestId("payout-filter-identity").click();
    await expect(page).toHaveURL(/blocked_on=identity/);
    await waitForQueueSettled(page);
    await expect(page.getByTestId(`payout-row-${sellerPayout.idempotency_key}`)).toHaveCount(0);

    await page.getByTestId("payout-filter-seller").click();
    await expect(page).toHaveURL(/blocked_on=seller/);
    await waitForQueueSettled(page);
    await expect(page.getByTestId(`payout-row-${identityPayout.idempotency_key}`)).toHaveCount(0);

    await page.getByTestId("payout-filter-all").click();
    await expect(page).not.toHaveURL(/blocked_on/);
    await waitForQueueSettled(page);
    await expect(page.getByTestId(`payout-row-${identityPayout.idempotency_key}`)).toBeVisible();
    await expect(page.getByTestId(`payout-row-${sellerPayout.idempotency_key}`)).toBeVisible();
  });

  test("두 대기가 서로 다른 것으로 읽힌다 — 같은 라벨·같은 클래스가 아니다", async ({ page }) => {
    const operator = seedE2eOperator({ username: `e2e-op-payoutdistinct-${Date.now()}` });
    const seeded = seedE2eOperatorQueues();
    const identityPayout = seeded.identity_pending_payout;
    const sellerPayout = seeded.seller_pending_payout;
    if (!identityPayout || !sellerPayout) {
      throw new Error("identity/seller 시드가 비어 있다");
    }

    await loginAsOperator(page, operator.username);
    await page.goto("/payouts");
    await waitForQueueSettled(page);

    const identityBadge = page
      .getByTestId(`payout-row-${identityPayout.idempotency_key}`)
      .getByTestId("payout-blocked-badge-identity");
    const sellerBadge = page
      .getByTestId(`payout-row-${sellerPayout.idempotency_key}`)
      .getByTestId("payout-blocked-badge-seller");

    await expect(identityBadge).toBeVisible();
    await expect(sellerBadge).toBeVisible();

    const identityText = (await identityBadge.textContent()) ?? "";
    const sellerText = (await sellerBadge.textContent()) ?? "";
    expect(identityText).not.toBe(sellerText);

    const identityClass = (await identityBadge.getAttribute("class")) ?? "";
    const sellerClass = (await sellerBadge.getAttribute("class")) ?? "";
    expect(identityClass).not.toBe(sellerClass);

    // 막힌 상태가 실패로 읽히지 않는다 — 오류·경고(role="alert")가 아니라
    // 대기로 그린다(#68 AC).
    await expect(identityBadge).not.toHaveAttribute("role", "alert");
    await expect(sellerBadge).not.toHaveAttribute("role", "alert");
    expect(identityText).not.toMatch(/실패|오류|에러/);
    expect(sellerText).not.toMatch(/실패|오류|에러/);
  });

  test("큐가 비어 있으면 명시적으로 말한다 — 빈 박스가 아니다", async ({ page }) => {
    clearE2eOperatorQueues();

    const operator = seedE2eOperator({ username: `e2e-op-payoutempty-${Date.now()}` });
    await loginAsOperator(page, operator.username);

    await page.goto("/payouts?blocked_on=identity");
    await waitForQueueSettled(page);

    await expect(page.getByTestId("payout-queue-empty")).toContainText("없습니다");
    await expect(page.getByTestId("payout-queue-error")).toHaveCount(0);
    await expect(page.getByTestId("payout-queue-list")).toHaveCount(0);
  });

  test("조회에 실패하면 실패라고 말한다 — 0건처럼 보이지 않는다", async ({ page }) => {
    const operator = seedE2eOperator({ username: `e2e-op-payoutfail-${Date.now()}` });

    await page.route("**/api/backend/operator/payouts*", (route) =>
      route.fulfill({ status: 500, body: JSON.stringify({ detail: "boom" }) }),
    );

    await loginAsOperator(page, operator.username);
    await page.goto("/payouts");
    await waitForQueueSettled(page);

    await expect(page.getByTestId("payout-queue-error")).toContainText("불러오지 못했습니다");
    await expect(page.getByTestId("payout-queue-empty")).toHaveCount(0);
    await expect(page.getByTestId("payout-queue-list")).toHaveCount(0);
  });

  test("홈의 두 지급 건수와 이 목록의 건수가 일치한다", async ({ page }) => {
    const operator = seedE2eOperator({ username: `e2e-op-payoutcount-${Date.now()}` });
    await loginAsOperator(page, operator.username);

    seedE2eOperatorQueues("identity");
    seedE2eOperatorQueues("seller");

    await page.reload();
    const identityHomeCount = await readHomeQueueValue(page, "queue-payouts-identity");
    const sellerHomeCount = await readHomeQueueValue(page, "queue-payouts-seller");

    await page.goto("/payouts?blocked_on=identity");
    await waitForQueueSettled(page);
    await expect(page.getByTestId("payout-queue-list").getByRole("listitem")).toHaveCount(
      identityHomeCount,
    );

    await page.goto("/payouts?blocked_on=seller");
    await waitForQueueSettled(page);
    await expect(page.getByTestId("payout-queue-list").getByRole("listitem")).toHaveCount(
      sellerHomeCount,
    );
  });

  test("세션이 없으면 렌더링 전에 로그인으로 돌아간다", async ({ page, context }) => {
    await context.clearCookies();
    await page.goto("/payouts");
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByTestId("payout-queue-heading")).toHaveCount(0);
  });
});
