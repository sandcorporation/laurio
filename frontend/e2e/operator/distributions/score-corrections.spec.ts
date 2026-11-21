import { expect, test } from "@playwright/test";

import {
  E2E_OPERATOR_PASSWORD,
  seedE2eOperator,
  seedE2eOperatorScoreCorrections,
} from "../../lib/seed-operator";
import { establishOperatorSession } from "../../lib/session";

// 운영자 앱 점수 정정 화면(#1183, 스펙 #1178). 사유 없이는 못 걸고, 걸면 새로고침해도 이력에 남는다.
// 「배분 끝남」 문구는 화면이 따로 판정하지 않고 API 의 `prize_settled` 를 따른다.

// 시험 하나 3초 한도 — 시드(채점까지 끝난 공모전 둘)는 beforeAll 이 따로 한다.
let operator: Awaited<ReturnType<typeof seedE2eOperator>>;
let seeded: Awaited<ReturnType<typeof seedE2eOperatorScoreCorrections>>;

test.beforeAll(async () => {
  [operator, seeded] = await Promise.all([seedE2eOperator(), seedE2eOperatorScoreCorrections()]);
});

test("사유 없이 정정을 못 걸고, 사유를 적고 걸면 이력에 남으며, 배분 전 공모전에는 배분 끝남 문구가 없다", async ({ page }) => {
  const [first] = seeded.open.submission_ids;
  await establishOperatorSession(
    page,
    operator.username,
    E2E_OPERATOR_PASSWORD,
    `/contests/${seeded.open.contest_id}/score-corrections`,
  );

  await expect(page.getByTestId("correction-settled-notice")).toHaveCount(0);
  await page.getByTestId(`correction-target-check-${first}`).check();
  await expect(page.getByTestId("correction-submit")).toBeDisabled();

  await page.getByTestId("correction-reason").fill("   ");
  await expect(page.getByTestId("correction-submit")).toBeDisabled();

  await page.getByTestId("correction-reason").fill("벤더 실패로 0% 가 굳었다");
  await expect(page.getByTestId("correction-submit")).toBeEnabled();
  await page.getByTestId("correction-submit").click();

  const rows = page.locator('[data-testid^="correction-row-"]');
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("벤더 실패로 0% 가 굳었다");
  await expect(rows.first()).toContainText(`#${first}`);

  await page.reload();
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("벤더 실패로 0% 가 굳었다");
});

test("배분이 끝난 공모전이면 정정 거는 버튼 앞에 「순위·돈은 바뀌지 않는다」가 보인다", async ({ page }) => {
  await establishOperatorSession(
    page,
    operator.username,
    E2E_OPERATOR_PASSWORD,
    `/contests/${seeded.settled.contest_id}/score-corrections`,
  );

  await expect(page.getByTestId("correction-settled-notice")).toHaveText(
    "배분이 끝난 공모전이다 — 순위·돈은 바뀌지 않는다",
  );
  await expect(page.getByTestId("correction-submit")).toBeVisible();
});
