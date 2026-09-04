// 이의 제기 화면 (#74) — 채점 결과를 보고, 이의를 걸고, 열람 기록을 확인한다.
//
// 시임은 실행 중인 공개 앱 하나다(ADR-0017/0021).
import { expect, test } from "@playwright/test";

import { seedE2eContests } from "./lib/seed";
import { establishDeveloperSession } from "./lib/session";

async function login(page: import("@playwright/test").Page, seed: string): Promise<void> {
  await establishDeveloperSession(page, seed);
}

test("내 참가 현황의 행에서 클릭으로 채점 결과에 도달한다", async ({ page }) => {
  const seeded = await seedE2eContests();
  await login(page, seeded.judging.developer_login_seed);

  await page.goto("/console/participation");
  const rows = page.getByTestId("participation-list").locator("li");
  await expect(rows.first()).toBeVisible();

  await rows.first().getByTestId(/participation-row-\d+-appeal/).click();

  await expect(page).toHaveURL(/\/console\/participation\/\d+\/appeal/);
  await expect(page.getByTestId("appeal-heading")).toBeVisible();
});

test("채점 결과와 이의 제기 폼이 함께 보인다 — 무엇에 이의를 거는지 보고 쓴다", async ({
  page,
}) => {
  const seeded = await seedE2eContests();
  await login(page, seeded.judging.developer_login_seed);

  await page.goto(`/console/participation/${seeded.judging.submissions[0].id}/appeal`);

  await expect(page.getByTestId("appeal-score-percentage")).not.toBeEmpty();
  // 근거가 없으면 무엇을 반박할지 모른다 — 폼만 있는 화면은 화면이 아니다.
  await expect(page.getByTestId("appeal-score-reasoning").locator("li").first()).toBeVisible();
  await expect(page.getByTestId("appeal-form")).toBeVisible();
});

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

test("채점 전이면 「아직 채점되지 않았다」고 말한다 — 실패로 보이지 않는다", async ({
  page,
}) => {
  const seeded = await seedE2eContests();
  await login(page, seeded.judging.developer_login_seed);

  const submissionId = seeded.judging.submissions[0].id;
  // 서버는 채점 전에 404 를 낸다(backend/tests/test_own_score.py 가 검증한다).
  // 여기서 확인할 것은 화면이 그 404 를 **실패가 아니라 순서**로 옮기는가다.
  await page.route(`**/api/backend/submissions/${submissionId}/score`, (route) =>
    route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "아직 채점되지 않았습니다." }),
    }),
  );

  await page.goto(`/console/participation/${submissionId}/appeal`);

  await expect(page.getByTestId("appeal-not-scored")).toBeVisible();
  await expect(page.getByTestId("appeal-error")).toHaveCount(0);
  await expect(page.getByTestId("appeal-form")).toHaveCount(0);
});

test("이의 기한이 화면에 있고, 지났으면 폼 대신 이유가 있다", async ({ page }) => {
  const seeded = await seedE2eContests();
  await login(page, seeded.judging.developer_login_seed);
  const submissionId = seeded.judging.submissions[0].id;

  // 기한 안 — 기한이 문장으로 보이고 폼이 있다. 기한을 만들어 놓고 화면에
  // 적지 않으면 달력을 든 사람에게만 유리한 함정이 된다.
  await page.goto(`/console/participation/${submissionId}/appeal`);
  await expect(page.getByTestId("appeal-deadline")).toBeVisible();
  await expect(page.getByTestId("appeal-form")).toBeVisible();

  // 기한 밖 — 서버가 `can_appeal: false` 를 준다. 버튼이 그냥 사라지면
  // "왜 없지"가 남는다: 이유를 말한다.
  await page.route(`**/api/backend/submissions/${submissionId}/score`, async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...body, can_appeal: false }),
    });
  });
  await page.goto(`/console/participation/${submissionId}/appeal`);

  await expect(page.getByTestId("appeal-closed")).toContainText("기한");
  await expect(page.getByTestId("appeal-form")).toHaveCount(0);
});

test("조회에 실패하면 실패했다고 말한다 — 「채점 전」처럼 보이지 않는다", async ({ page }) => {
  const seeded = await seedE2eContests();
  await login(page, seeded.judging.developer_login_seed);

  const submissionId = seeded.judging.submissions[0].id;
  await page.route(`**/api/backend/submissions/${submissionId}/score`, (route) =>
    route.fulfill({ status: 500, contentType: "application/json", body: "{}" }),
  );

  await page.goto(`/console/participation/${submissionId}/appeal`);

  await expect(page.getByTestId("appeal-error")).toBeVisible();
  await expect(page.getByTestId("appeal-not-scored")).toHaveCount(0);
});

test("열람 기록 조회가 실패하면 「아무도 안 봤다」고 하지 않는다", async ({ page }) => {
  const seeded = await seedE2eContests();
  await login(page, seeded.judging.developer_login_seed);

  const submissionId = seeded.judging.submissions[0].id;
  // **채점 결과는 그대로 두고 열람 기록만 죽인다** — 이 화면이 지키는 약속이
  // "열람은 반드시 기록된다"이므로, 기록을 못 읽은 것이 0건으로 보이면 그
  // 약속이 조용히 거짓말이 된다.
  await page.route(`**/api/backend/submissions/${submissionId}/source-readings*`, (route) =>
    route.fulfill({ status: 500, contentType: "application/json", body: "{}" }),
  );
  // 채점 결과가 있어야 열람 기록 구역까지 그려진다.
  await page.route(`**/api/backend/submissions/${submissionId}/score`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        percentage: "80.00",
        model_version: "fake-llm-v1",
        reasoning: [{ requirement_id: 1, is_met: true, reasoning: "충족" }],
        created_at: new Date().toISOString(),
      }),
    }),
  );

  await page.goto(`/console/participation/${submissionId}/appeal`);

  await expect(page.getByTestId("appeal-readings-error")).toBeVisible();
  await expect(page.getByTestId("appeal-readings-empty")).toHaveCount(0);
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

test("내 이의가 배분을 붙잡고 있으면 그렇게 말한다 — 사라진 게 아니다", async ({ page }) => {
  const seeded = await seedE2eContests();
  await login(page, seeded.judging.developer_login_seed);
  const submissionId = seeded.judging.submissions[0].id;

  await page.route(`**/api/backend/submissions/${submissionId}/appeal`, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        submission_id: submissionId,
        reason: "컷라인 판정에 이의가 있습니다.",
        status: "pending",
        ruling_note: "",
        correction_amount: null,
        ruled_at: null,
        created_at: new Date().toISOString(),
        is_holding_distribution: true,
      }),
    });
  });

  await page.goto(`/console/participation/${submissionId}/appeal`);

  // 침묵은 상금이 사라진 것으로 읽힌다(ADR-0020).
  await expect(page.getByTestId("appeal-existing-holding")).toContainText("그대로 남아");
});

test("세션이 없으면 렌더링 전에 로그인으로 돌아간다", async ({ page }) => {
  const response = await page.goto("/console/participation/1/appeal");

  expect(response?.status()).toBeLessThan(400);
  await expect(page).toHaveURL(/\/login/);
  expect(await page.content()).not.toContain("채점 결과와 이의 제기");
});
