import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import {
  E2E_OPERATOR_PASSWORD,
  clearE2eOperatorQueues,
  seedE2eOperator,
  seedE2eOperatorQueues,
} from "../lib/seed-operator";
import { establishOperatorSession } from "../lib/session";

// 운영자 앱 07(#65) — 「할 일」 홈의 세 큐 건수(ADR-0020).
//
// 시임 규약(ADR-0021)을 그대로 따른다 — 화면 렌더링·클릭은 `page`로, 세션 만료
// 같은 순수 HTTP 판정은 raw `request`로 친다. 세 큐 데이터는 시드 명령이
// **멱등하지 않게** 심으므로(seed_e2e_operator_queues.py 상단 주석), 이 파일의
// 단언은 절대 절대값을 가정하지 않고 항상 "부르기 전 대비 증분"이나 "명시적으로
// 비운 뒤의 0"으로만 검증한다.

async function loginAsOperator(page: Page, username: string): Promise<void> {
  await establishOperatorSession(page, username, E2E_OPERATOR_PASSWORD);
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
});

test.describe("각 건수가 자기 목록으로 이어진다", () => {
  test("이의 큐 카드를 클릭하면 이의 목록 경로로 이동한다", async ({ page }) => {
    const operator = await seedE2eOperator();
    await loginAsOperator(page, operator.username);

    await readQueueValue(page, "queue-appeals-pending"); // 로딩이 끝나길 기다린다.
    await page.getByTestId("queue-appeals-pending").click();
    await expect(page).toHaveURL(/\/appeals\?status=pending/);
  });

});

test.describe("세션 만료(ADR-0016/0019)", () => {
});
