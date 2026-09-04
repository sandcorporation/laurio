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

  test("필터가 실제로 배제한다 — identity로 걸러도 seller 행은 보이지 않는다(그 반대도)", async ({
    page,
  }) => {
    const operator = await seedE2eOperator();
    const seeded = await seedE2eOperatorQueues();
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
    const operator = await seedE2eOperator();
    const seeded = await seedE2eOperatorQueues();
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
    const operator = await seedE2eOperator();
    const seeded = await seedE2eOperatorQueues();
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

  test("필터를 바꾸는 순간에도 이전 필터의 행이 새 탭 아래 보이지 않는다", async ({ page }) => {
    // 코드리뷰 지적 — Playwright의 auto-retry는 다음 프레임을 기다려 주므로,
    // 이 상태를 "한 프레임"으로만 재현하면 이 테스트조차 통과시켜 버린다.
    // 그래서 seller 응답만 인위적으로 지연시켜, 그 전환 구간을 사람이 눈으로도
    // 볼 수 있을 만큼(수백 ms 이상) 늘려 놓고 그 구간 전체에서 잘못된 조합이
    // 없다는 것을 단언한다 — auto-retry를 우회하는 것이 아니라, auto-retry가
    // 절대 놓칠 수 없을 만큼 창을 넓히는 쪽이다.
    const operator = await seedE2eOperator();
    const seeded = await seedE2eOperatorQueues();
    const identityPayout = seeded.identity_pending_payout;
    const sellerPayout = seeded.seller_pending_payout;
    if (!identityPayout || !sellerPayout) {
      throw new Error("identity/seller 시드가 비어 있다");
    }

    await loginAsOperator(page, operator.username);
    await page.goto("/payouts?blocked_on=identity");
    await waitForQueueSettled(page);
    await expect(page.getByTestId(`payout-row-${identityPayout.idempotency_key}`)).toBeVisible();

    // seller 쪽 응답만 늦춘다 — identity 쪽은 이미 화면에 반영된 뒤라 건드릴
    // 필요가 없다(kindsFor("seller")가 seller 하나만 부른다는 것을 이 지연이
    // 그대로 이용한다).
    await page.route("**/api/backend/operator/payouts?blocked_on=seller*", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      await route.continue();
    });

    await page.getByTestId("payout-filter-seller").click();

    // 지연된 응답이 아직 오지 않은 이 구간(최대 1.5초) 내내 — 렌더 직후부터
    // 반복해서 — identity 행이 seller 탭 아래 남아 있으면 안 된다. 이 저장소가
    // 겪은 트랩(포함만 확인하면 깨진 필터를 못 잡는다)과 대칭으로, 여기서는
    // "없어야 할 것이 없다"를 전환 구간 내내 반복 확인한다.
    for (let i = 0; i < 5; i += 1) {
      await expect(page.getByTestId(`payout-row-${identityPayout.idempotency_key}`)).toHaveCount(0);
      await expect(page.getByTestId(`payout-blocked-badge-identity`)).toHaveCount(0);
      await page.waitForTimeout(200);
    }

    // 지연이 끝나면 seller 행이 정상적으로 나타난다 — 전환이 로딩에서 끝난
    // 것이 아니라 실제 데이터로 이어졌다는 것도 같이 확인한다.
    await expect(page.getByTestId(`payout-row-${sellerPayout.idempotency_key}`)).toBeVisible({
      timeout: 5000,
    });
    await expect(page.getByTestId(`payout-row-${identityPayout.idempotency_key}`)).toHaveCount(0);
  });

  test("큐가 비어 있으면 명시적으로 말한다 — 빈 박스가 아니다", async ({ page }) => {
    await clearE2eOperatorQueues();

    const operator = await seedE2eOperator();
    await loginAsOperator(page, operator.username);

    await page.goto("/payouts?blocked_on=identity");
    await waitForQueueSettled(page);

    await expect(page.getByTestId("payout-queue-empty")).toContainText("없습니다");
    await expect(page.getByTestId("payout-queue-error")).toHaveCount(0);
    await expect(page.getByTestId("payout-queue-list")).toHaveCount(0);
  });

  test("조회에 실패하면 실패라고 말한다 — 0건처럼 보이지 않는다", async ({ page }) => {
    const operator = await seedE2eOperator();

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
    const operator = await seedE2eOperator();
    await loginAsOperator(page, operator.username);

    await seedE2eOperatorQueues("identity");
    await seedE2eOperatorQueues("seller");

    await page.reload();
    const identityHomeCount = await readHomeQueueValue(page, "queue-payouts-identity");
    const sellerHomeCount = await readHomeQueueValue(page, "queue-payouts-seller");

    // **보이는 행 수가 아니라 전체 건수와 맞춘다**(#149). 목록이 페이지로 잘리면서
    // 그 둘이 갈렸다 — 20건을 넘는 순간 「보이는 행 수」로 맞추면 홈이 틀렸다고
    // 말하게 되고, 실제로 틀린 것은 비교 대상이다.
    await page.goto("/payouts?blocked_on=identity");
    await waitForQueueSettled(page);
    await expect(page.getByTestId("payout-queue-total-count")).toHaveText(
      String(identityHomeCount),
    );

    await page.goto("/payouts?blocked_on=seller");
    await waitForQueueSettled(page);
    await expect(page.getByTestId("payout-queue-total-count")).toHaveText(String(sellerHomeCount));
  });

  test("세션이 없으면 렌더링 전에 로그인으로 돌아간다", async ({ page, context }) => {
    await context.clearCookies();
    await page.goto("/payouts");
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByTestId("payout-queue-heading")).toHaveCount(0);
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

  test("실이체 대기 배지도 칠해진다 — 무스타일 본문 텍스트가 아니다", async ({ page }) => {
    const operator = await seedE2eOperator();
    await loginAsOperator(page, operator.username);

    await page.route("**/api/backend/operator/payouts?blocked_on=transfer*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        // 페이지네이션이 붙어(#149) 본문이 `{items, count}` 다.
        body: JSON.stringify({ items: [TRANSFER_ROW], count: 1 }),
      }),
    );

    await page.goto("/payouts?blocked_on=transfer");
    await waitForQueueSettled(page);

    const badge = page.getByTestId("payout-blocked-badge-transfer");
    await expect(badge).toBeVisible();

    // 배경이 투명하면 배지가 아니다 — 다른 두 종류는 각자 배경·테두리를 갖는다.
    const background = await badge.evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(background).not.toBe("rgba(0, 0, 0, 0)");
    expect(background).not.toBe("transparent");

    // 그리고 다른 두 종류와 같은 색이어서도 안 된다 — 뭉뚱그리지 않는다(#68 AC).
    const identityBackground = await badge.evaluate((el) => {
      const probe = document.createElement("span");
      probe.className = "badge-waiting badge-waiting-identity";
      el.parentElement?.appendChild(probe);
      const value = getComputedStyle(probe).backgroundColor;
      probe.remove();
      return value;
    });
    expect(background).not.toBe(identityBackground);
  });
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

  test("「전체」 탭이 요청 하나만 낸다 — 셋을 합쳐 브라우저에서 정렬하지 않는다", async ({
    page,
  }) => {
    const operator = await seedE2eOperator();
    await seedE2eOperatorQueues();
    await loginAsOperator(page, operator.username);

    const seen = countQueueRequests(page);
    await page.goto("/payouts");
    await waitForQueueSettled(page);

    const listRequests = seen.urls.filter((url) => !url.includes("/payouts/counts"));
    expect(listRequests).toHaveLength(1);
    expect(listRequests[0]).not.toContain("blocked_on=");
  });

  test("운영자 홈은 목록을 받아 세지 않는다 — 건수는 건수로 묻는다", async ({ page }) => {
    const operator = await seedE2eOperator();
    await seedE2eOperatorQueues();

    const seen = countQueueRequests(page);
    await loginAsOperator(page, operator.username);
    await expect(page.getByTestId("queue-payouts-seller-count").or(page.getByTestId("queue-payouts-seller-empty"))).toBeVisible();

    expect(seen.urls.filter((url) => url.includes("blocked_on="))).toEqual([]);
    expect(seen.urls.some((url) => url.includes("/payouts/counts"))).toBe(true);
  });

  test("한 페이지를 넘는 큐는 잘렸다고 말하고, 더 보기가 이어 붙인다", async ({ page }) => {
    // 21건을 실제로 심으려면 공모전 21개를 개최·심사·선정해야 한다 — 여기서 볼 것은
    // 백엔드의 자르기가 아니라(그건 backend/tests 가 본다) **잘린 사실이 화면에
    // 드러나고 나머지에 도달할 길이 있는가**다. 그래서 응답을 갈아끼운다.
    const operator = await seedE2eOperator();
    await loginAsOperator(page, operator.username);

    const row = (index: number) => ({
      idempotency_key: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
      contest_id: 1000 + index,
      developer_user_id: 1,
      net_amount: 856_000,
      status: "confirmed_seller_pending",
      transfer_status: "not_requested",
      blocked_on: "seller",
      seller_status: "pending",
      has_identity: true,
      created_at: new Date().toISOString(),
    });

    await page.route("**/api/backend/operator/payouts?page=*", (route) => {
      const page2 = route.request().url().includes("page=2");
      const items = page2
        ? [row(21), row(22), row(23), row(24), row(25)]
        : Array.from({ length: 20 }, (_unused, index) => row(index + 1));
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items, count: 25 }),
      });
    });

    await page.goto("/payouts");
    await waitForQueueSettled(page);

    // 잘렸다는 사실이 화면에 있다 — 「20건」이 전부인 것처럼 보이지 않는다.
    await expect(page.getByTestId("payout-queue-total-count")).toHaveText("25");
    await expect(page.getByTestId("payout-queue-list").getByRole("listitem")).toHaveCount(20);

    await page.getByTestId("payout-queue-load-more").click();

    // **이어 붙는다.** 갈아끼우면 「더 보기」가 앞 페이지를 지운다.
    await expect(page.getByTestId("payout-queue-list").getByRole("listitem")).toHaveCount(25);
    await expect(page.getByTestId("payout-queue-load-more")).toHaveCount(0);
  });

  test("「더 보기」로 2페이지까지 본 뒤 필터를 바꾸면 페이지가 1로 돌아간다", async ({
    page,
  }) => {
    // 쌓아 둔 페이지는 **경로에 딸린 상태**다(#149). 그 사실이 코드에 없으면, 2페이지를
    // 보던 중 필터를 바꿨을 때 새 필터의 **2페이지**를 받아 옛 목록 뒤에 이어 붙인다 —
    // 운영자가 보는 것은 두 필터가 섞인, 어느 쪽으로도 참이 아닌 목록이다.
    const operator = await seedE2eOperator();
    await loginAsOperator(page, operator.username);

    const row = (key: string, blockedOn: string) => ({
      idempotency_key: key,
      contest_id: 1,
      developer_user_id: 1,
      net_amount: 100,
      status: "confirmed_seller_pending",
      transfer_status: "not_requested",
      blocked_on: blockedOn,
      seller_status: "pending",
      has_identity: true,
      created_at: new Date().toISOString(),
    });
    const identityRow = (index: number) =>
      row(`11111111-0000-4000-8000-${String(index).padStart(12, "0")}`, "identity");
    const sellerRow = (index: number) =>
      row(`22222222-0000-4000-8000-${String(index).padStart(12, "0")}`, "seller");

    await page.route("**/api/backend/operator/payouts?*", (route) => {
      const url = route.request().url();
      const make = url.includes("blocked_on=seller") ? sellerRow : identityRow;
      const secondPage = url.includes("page=2");
      const items = secondPage
        ? [make(21), make(22)]
        : Array.from({ length: 20 }, (_unused, index) => make(index + 1));
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items, count: 22 }),
      });
    });

    await page.goto("/payouts?blocked_on=identity");
    await waitForQueueSettled(page);
    await page.getByTestId("payout-queue-load-more").click();
    await expect(page.getByTestId("payout-queue-list").getByRole("listitem")).toHaveCount(22);

    await page.getByTestId("payout-filter-seller").click();

    // seller 의 **1페이지**만 보인다 — 2페이지를 받아 이어 붙이지 않았다.
    await expect(page.getByTestId("payout-queue-list").getByRole("listitem")).toHaveCount(20);
    await expect(page.getByTestId("payout-row-11111111-0000-4000-8000-000000000001")).toHaveCount(0);
    await expect(page.getByTestId("payout-row-22222222-0000-4000-8000-000000000001")).toBeVisible();
  });

  test("필터를 바꾸면 앞 필터에서 쌓아 둔 페이지를 버린다", async ({ page }) => {
    // 「더 보기」로 2페이지까지 본 뒤 필터를 바꾸면, 새 필터의 2페이지를 옛 목록 뒤에
    // 이어 붙이는 것이 예전 `usePagedList` 의 동작이었다(#149) — 호출부 둘이 고정
    // 경로라 드러나지 않았을 뿐이다.
    const operator = await seedE2eOperator();
    await loginAsOperator(page, operator.username);

    const row = (key: string, blockedOn: string) => ({
      idempotency_key: key,
      contest_id: 1,
      developer_user_id: 1,
      net_amount: 100,
      status: "confirmed_seller_pending",
      transfer_status: "not_requested",
      blocked_on: blockedOn,
      seller_status: "pending",
      has_identity: true,
      created_at: new Date().toISOString(),
    });

    await page.route("**/api/backend/operator/payouts?*", (route) => {
      const url = route.request().url();
      const seller = url.includes("blocked_on=seller");
      const items = seller
        ? [row("aaaaaaaa-0000-4000-8000-000000000001", "seller")]
        : [row("bbbbbbbb-0000-4000-8000-000000000002", "identity")];
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items, count: 1 }),
      });
    });

    await page.goto("/payouts?blocked_on=identity");
    await waitForQueueSettled(page);
    await expect(
      page.getByTestId("payout-row-bbbbbbbb-0000-4000-8000-000000000002"),
    ).toBeVisible();

    await page.getByTestId("payout-filter-seller").click();

    await expect(page.getByTestId("payout-row-aaaaaaaa-0000-4000-8000-000000000001")).toBeVisible();
    await expect(page.getByTestId("payout-row-bbbbbbbb-0000-4000-8000-000000000002")).toHaveCount(0);
    await expect(page.getByTestId("payout-queue-list").getByRole("listitem")).toHaveCount(1);
  });
});
