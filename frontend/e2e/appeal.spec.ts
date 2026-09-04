// 이의 제기 화면 (#74) — 채점 결과를 보고, 이의를 걸고, 열람 기록을 확인한다.
//
// 시임은 실행 중인 공개 앱 하나다(ADR-0017/0021).
import { expect, test } from "@playwright/test";

import { seedE2eContests } from "./lib/seed";
import { establishDeveloperSession } from "./lib/session";

async function login(page: import("@playwright/test").Page, seed: string): Promise<void> {
  await establishDeveloperSession(page, seed);
}

test("이의를 접수하면 폼이 사라지고 접수된 이의가 보인다", async ({ page }) => {
  const seeded = await seedE2eContests();
  await login(page, seeded.judging.developer_login_seed);

  await page.goto(`/console/participation/${seeded.judging.submissions[0].id}/appeal`);
  await page.getByTestId("appeal-reason").fill("필수 요건 2번의 Evidence 가 소스에 실제로 있습니다.");
  await page.getByTestId("appeal-submit").click();

  // **낙관적 갱신이 아니다** — 서버에서 다시 읽은 결과라야 한다. 한 Submission
  // 에 이의는 하나뿐이고 되돌릴 수 없어서, 접수됐다고 먼저 그렸다가 틀리면
  // 낸 적 없는 이의를 봤다고 믿게 된다.
  await expect(page.getByTestId("appeal-existing")).toBeVisible();
  await expect(page.getByTestId("appeal-existing-reason")).toContainText("Evidence");
  await expect(page.getByTestId("appeal-form")).toHaveCount(0);

  // 새로고침해도 그대로다 — 서버에 실제로 남았다는 뜻이다.
  await page.reload();
  await expect(page.getByTestId("appeal-existing")).toBeVisible();
});

test("남의 제출이면 채점 결과가 보이지 않는다", async ({ page }) => {
  const seeded = await seedE2eContests();
  // 시드의 다른 개발자로 로그인해 남의 submission 을 직접 친다.
  await login(page, `e2e-appeal-intruder-${Date.now()}`);

  await page.goto(`/console/participation/${seeded.judging.submissions[0].id}/appeal`);

  // 403 은 404 와 달리 "화면 전체가 실패" 다 — 남의 점수가 새지 않는다.
  await expect(page.getByTestId("appeal-error")).toBeVisible();
  await expect(page.getByTestId("appeal-score")).toHaveCount(0);
});
