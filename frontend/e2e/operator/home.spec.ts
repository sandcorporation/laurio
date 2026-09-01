import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import {
  E2E_OPERATOR_PASSWORD,
  clearE2eOperatorQueues,
  seedE2eOperator,
  seedE2eOperatorQueues,
} from "../lib/seed-operator";

// 운영자 앱 07(#65) — 「할 일」 홈의 세 큐 건수(ADR-0020).
//
// 시임 규약(ADR-0021)을 그대로 따른다 — 화면 렌더링·클릭은 `page`로, 세션 만료
// 같은 순수 HTTP 판정은 raw `request`로 친다. 세 큐 데이터는 시드 명령이
// **멱등하지 않게** 심으므로(seed_e2e_operator_queues.py 상단 주석), 이 파일의
// 단언은 절대 절대값을 가정하지 않고 항상 "부르기 전 대비 증분"이나 "명시적으로
// 비운 뒤의 0"으로만 검증한다.

async function loginAsOperator(page: Page, username: string): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("login-username").fill(username);
  await page.getByTestId("login-password").fill(E2E_OPERATOR_PASSWORD);
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("operator-home-heading")).toBeVisible();
}

/** 큐 카드 하나의 현재 표시값을 읽는다 — "-count"(양수)나 "-empty"(0) 중 어느 쪽이
 * 떴는지로 판정한다. 로딩이 끝날 때까지는 둘 다 없으므로 Playwright의 자동
 * 대기가 자연히 로딩 완료를 기다리게 만든다. */
async function readQueueValue(page: Page, testId: string): Promise<number> {
  const countLocator = page.getByTestId(`${testId}-count`);
  const emptyLocator = page.getByTestId(`${testId}-empty`);
  await expect(countLocator.or(emptyLocator)).toBeVisible();

  if ((await emptyLocator.count()) > 0) return 0;
  const text = await countLocator.textContent();
  return Number.parseInt(text ?? "0", 10);
}

test.describe("세 큐 건수 — 정확성(ADR-0020)", () => {
  test("실제로 심은 뒤 홈의 세 숫자가 그것과 정확히 맞는다", async ({ page }) => {
    const operator = seedE2eOperator();
    await loginAsOperator(page, operator.username);

    const before = {
      appeals: await readQueueValue(page, "queue-appeals-pending"),
      identity: await readQueueValue(page, "queue-payouts-identity"),
      seller: await readQueueValue(page, "queue-payouts-seller"),
    };

    seedE2eOperatorQueues();

    await page.reload();
    const after = {
      appeals: await readQueueValue(page, "queue-appeals-pending"),
      identity: await readQueueValue(page, "queue-payouts-identity"),
      seller: await readQueueValue(page, "queue-payouts-seller"),
    };

    expect(after.appeals).toBe(before.appeals + 1);
    expect(after.identity).toBe(before.identity + 1);
    expect(after.seller).toBe(before.seller + 1);
  });

  test("0건은 0건이라고 명시적으로 말한다 — 빈 영역이 아니다", async ({ page }) => {
    clearE2eOperatorQueues();

    const operator = seedE2eOperator();
    await loginAsOperator(page, operator.username);

    await expect(page.getByTestId("queue-appeals-pending-empty")).toContainText("처리할 것이 없습니다");
    await expect(page.getByTestId("queue-payouts-identity-empty")).toContainText("처리할 것이 없습니다");
    await expect(page.getByTestId("queue-payouts-seller-empty")).toContainText("처리할 것이 없습니다");

    // 0건과 조회 실패가 같은 표식을 쓰지 않는다는 것도 여기서 같이 확인한다.
    await expect(page.getByTestId("queue-appeals-pending-error")).toHaveCount(0);
  });

  test("조회 실패는 실패라고 말한다 — 0건처럼 보이지 않는다", async ({ page }) => {
    const operator = seedE2eOperator();

    // 세 큐 조회만 실패시킨다 — 세션 확인(/api/auth/session)이나 로그인 자체는
    // 그대로 실제 백엔드를 친다(ADR-0017은 SSR·가드·허용목록/Origin 검증이라는
    // 세 가지 실제 위험을 모킹 없이 지키라는 규율이다; 이 조회 실패 분기는 그
        // 위험 중 어디에도 해당하지 않는 순수 프론트 렌더링 상태이므로, 이 요청
    // 셋만 좁혀 가짜 500으로 응답해 "실패"라는 상태를 결정적으로 재현한다).
    await page.route("**/api/backend/operator/appeals*", (route) =>
      route.fulfill({ status: 500, body: JSON.stringify({ detail: "boom" }) }),
    );
    await page.route("**/api/backend/operator/payouts*", (route) =>
      route.fulfill({ status: 500, body: JSON.stringify({ detail: "boom" }) }),
    );

    await loginAsOperator(page, operator.username);

    await expect(page.getByTestId("queue-appeals-pending-error")).toContainText("불러오지 못했습니다");
    await expect(page.getByTestId("queue-payouts-identity-error")).toContainText("불러오지 못했습니다");
    await expect(page.getByTestId("queue-payouts-seller-error")).toContainText("불러오지 못했습니다");

    // 실패가 0건으로 잘못 보이지 않는다.
    await expect(page.getByTestId("queue-appeals-pending-empty")).toHaveCount(0);
    await expect(page.getByTestId("queue-appeals-pending-count")).toHaveCount(0);
  });
});

test.describe("각 건수가 자기 목록으로 이어진다", () => {
  test("이의 큐 카드를 클릭하면 이의 목록 경로로 이동한다", async ({ page }) => {
    const operator = seedE2eOperator();
    await loginAsOperator(page, operator.username);

    await readQueueValue(page, "queue-appeals-pending"); // 로딩이 끝나길 기다린다.
    await page.getByTestId("queue-appeals-pending").click();
    await expect(page).toHaveURL(/\/appeals\?status=pending/);
  });

  test("신원 대기 지급 카드를 클릭하면 payouts?blocked_on=identity로 이동한다", async ({
    page,
  }) => {
    const operator = seedE2eOperator();
    await loginAsOperator(page, operator.username);

    await readQueueValue(page, "queue-payouts-identity");
    await page.getByTestId("queue-payouts-identity").click();
    await expect(page).toHaveURL(/\/payouts\?blocked_on=identity/);
  });

  test("Seller 대기 지급 카드를 클릭하면 payouts?blocked_on=seller로 이동한다", async ({
    page,
  }) => {
    const operator = seedE2eOperator();
    await loginAsOperator(page, operator.username);

    await readQueueValue(page, "queue-payouts-seller");
    await page.getByTestId("queue-payouts-seller").click();
    await expect(page).toHaveURL(/\/payouts\?blocked_on=seller/);
  });
});

test.describe("세션 만료(ADR-0016/0019)", () => {
  test("세션이 만료되어 조회가 거절되면 로그인 화면으로 돌아간다 — 깨진 화면이 남지 않는다", async ({
    page,
    context,
  }) => {
    const operator = seedE2eOperator();
    await loginAsOperator(page, operator.username);

    // 서버 쪽에서 세션이 무효화된 것과 같은 효과를 브라우저 쪽에서 흉내낸다 —
    // 쿠키 값을 있을 법하지 않은 값으로 바꿔 백엔드가 더는 이 세션을 인식하지
    // 못하게 만든다(frontend/e2e/operator/auth.spec.ts와 다른 시나리오: 여기서는
        // 홈이 이미 렌더된 뒤 큐 조회 도중 만료되는 경우를 흉내낸다).
    await context.addCookies([
      { name: "laurio_operator_session", value: "expired-session-9134", url: page.url() },
    ]);
    await page.reload();

    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByTestId("operator-home-protected-content")).toHaveCount(0);
  });
});
