// 개최자의 제출 명단 (#956, ADR-0079) — 콘솔 「내 공모전」에서 클릭으로 닿고, 표시 이름·
// 제출 시각만 보인다.
//
// 마감 전 응답의 칸·소유권 경계는 backend/tests/test_submission_roster.py 가 실물로
// 검증한다. 여기서는 화면이 백엔드가 준 이름을 그대로 그리고, 상세로 가는 길(제출 id·
// 링크)과 민감 값이 화면에 없는지를 본다(ADR-0017/0021).
import { expect, test } from "@playwright/test";

import { seedE2eContests } from "../lib/seed";
import { establishDeveloperSession } from "../lib/session";

test("개최자는 내 공모전에서 제출 명단으로 가 표시 이름만 본다", async ({ page }) => {
  const seeded = await seedE2eContests();
  const contest = seeded.judging;
  await establishDeveloperSession(page, contest.sponsor_login_seed);

  await page.goto("/console/contests");
  await page.getByTestId(`my-contest-row-${contest.id}-roster`).click();

  await expect(page.getByTestId("roster-table")).toBeVisible();
  await expect(page.getByTestId("roster-count")).toHaveText(String(contest.submissions.length));
  await expect(page.getByTestId("roster-row")).toHaveCount(contest.submissions.length);
  for (const submission of contest.submissions) {
    await expect(page.getByTestId("roster-table")).toContainText(submission.developer_display_name);
  }
  // 상세로 가는 길이 없다 — 링크가 하나도 없고, 민감 값도 없다.
  await expect(page.getByTestId("roster-table").locator("a")).toHaveCount(0);
  const body = await page.content();
  expect(body).not.toContain(contest.sensitive_test_account);
  expect(body).not.toContain(contest.sensitive_source_object_key_a);
  expect(body).not.toContain(contest.sensitive_score_model_version);
});

test("남의 공모전 명단으로는 닿을 수 없다", async ({ page }) => {
  const seeded = await seedE2eContests();
  await establishDeveloperSession(page, seeded.judging.sponsor_login_seed);

  await page.goto(`/console/contests/${seeded.funded.id}/roster`);

  await expect(page.getByTestId("roster-forbidden")).toBeVisible();
  await expect(page.getByTestId("roster-table")).toHaveCount(0);
});
