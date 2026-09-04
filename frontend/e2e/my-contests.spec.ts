// 「내 공모전」 (#81) — Sponsor 가 자기가 연 공모전과 각각의 「다음 행동」을 본다.
//
// 시임은 실행 중인 공개 앱 하나다(ADR-0017/0021). 「다음 행동」이 각 단계에서
// 무엇이 되는지는 backend/tests/test_my_contests.py 가 실물로 검증한다 — 여기서
// 확인할 것은 화면이 그 값을 어떻게 구분해 보여주는가다.
import { expect, test } from "@playwright/test";

import { seedE2eContests } from "./lib/seed";
import { establishDeveloperSession } from "./lib/session";

async function login(page: import("@playwright/test").Page, seed: string): Promise<void> {
  await establishDeveloperSession(page, seed);
}

test("연 공모전이 없으면 빈 목록이라고 말한다 — 조회 실패와 구별된다", async ({ page }) => {
  await login(page, `e2e-sponsor-empty-${Date.now()}`);

  await page.goto("/console/contests");

  await expect(page.getByTestId("my-contests-heading")).toBeVisible();
  await expect(page.getByTestId("my-contests-empty")).toContainText("아직 연 공모전이 없습니다");
  await expect(page.getByTestId("my-contests-error")).toHaveCount(0);
});

test("조회에 실패하면 실패했다고 말한다 — 0건처럼 보이지 않는다", async ({ page }) => {
  await login(page, `e2e-sponsor-error-${Date.now()}`);

  await page.route("**/api/backend/contests/mine*", (route) =>
    route.fulfill({ status: 500, contentType: "application/json", body: "{}" }),
  );

  await page.goto("/console/contests");

  await expect(page.getByTestId("my-contests-error")).toBeVisible();
  await expect(page.getByTestId("my-contests-empty")).toHaveCount(0);
});

test("홈에서 클릭으로 도달한다 — URL 을 직접 쳐야만 닿는 화면이 아니다", async ({ page }) => {
  await login(page, `e2e-sponsor-link-${Date.now()}`);

  await page.getByTestId("app-home-my-contests-link").click();

  await expect(page).toHaveURL(/\/console\/contests/);
  await expect(page.getByTestId("my-contests-heading")).toBeVisible();
});

test("내가 연 공모전이 행으로 보이고 「다음 행동」을 먼저 말한다", async ({ page }) => {
  // 시드가 만든 심사 Contest 의 진짜 Sponsor 로 로그인한다.
  const seeded = await seedE2eContests();
  await login(page, seeded.judging.sponsor_login_seed);

  await page.goto("/console/contests");

  const row = page.getByTestId(`my-contest-row-${seeded.judging.id}`);
  await expect(row).toBeVisible();
  // 값 자체는 서버가 판정한다 — 화면은 그것을 문구로 옮길 뿐이고, 어떤 값이든
  // 「알 수 없음」으로 떨어지지 않는 것이 여기서 확인할 것이다.
  expect(await row.getAttribute("data-next-action")).toBeTruthy();
  await expect(
    page.getByTestId(`my-contest-row-${seeded.judging.id}-next-action`),
  ).not.toBeEmpty();
  // 몇 명이 냈는지가 그 자리에 있어야 심사하러 갈지 판단할 수 있다.
  await expect(
    page.getByTestId(`my-contest-row-${seeded.judging.id}-submission-count`),
  ).toHaveText("2");
});

test("심사할 수 있는 단계면 심사 화면으로 클릭해 들어간다", async ({ page }) => {
  const seeded = await seedE2eContests();
  await login(page, seeded.judging.sponsor_login_seed);

  await page.goto("/console/contests");
  await page.getByTestId(`my-contest-row-${seeded.judging.id}-judge`).click();

  await expect(page).toHaveURL(new RegExp(`/console/contests/${seeded.judging.id}/judge`));
});

test("심사할 수 없는 단계에는 심사 링크가 없다", async ({ page }) => {
  const seeded = await seedE2eContests();
  await login(page, seeded.judging.sponsor_login_seed);

  // 배분 대기는 심사가 끝난 뒤다 — 링크를 걸어 두면 눌러 봐야 보여줄 것이 없다.
  await page.route("**/api/backend/contests/mine*", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...body,
        items: body.items.map((row: Record<string, unknown>) => ({
          ...row,
          next_action: "awaiting_distribution",
        })),
      }),
    });
  });

  await page.goto("/console/contests");

  await expect(page.getByTestId(`my-contest-row-${seeded.judging.id}`)).toBeVisible();
  await expect(page.getByTestId(`my-contest-row-${seeded.judging.id}-judge`)).toHaveCount(0);
});

test("이의로 배분이 보류된 공모전은 「보류」라고 말한다 — 조용히 늦은 게 아니다", async ({
  page,
}) => {
  // 이 스토리(40)가 #81 의 존재 이유다. 플래그가 **언제** 참이 되는지는
  // backend/tests/test_my_contests.py 가 실물로 친다 — 참으로 만들려면 전역
  // 시계를 심사기간 + 배분 대기일만큼 밀어야 하고, 그러면 같은 실행의 다른
  // 스펙이 함께 움직인다.
  const seeded = await seedE2eContests();
  await login(page, seeded.judging.sponsor_login_seed);

  await page.route("**/api/backend/contests/mine*", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...body,
        items: body.items.map((row: Record<string, unknown>) => ({
          ...row,
          next_action: "awaiting_appeal_ruling",
        })),
      }),
    });
  });

  await page.goto("/console/contests");

  // 「배분 대기」와 문구가 달라야 한다 — 같으면 #81 이 하려던 구분이 사라진다.
  await expect(
    page.getByTestId(`my-contest-row-${seeded.judging.id}-next-action`),
  ).toContainText("이의 심판");
});

test("20개를 넘으면 「더 보기」로 나머지에 도달한다 — 잘린 채 끝나지 않는다", async ({
  page,
}) => {
  const seeded = await seedE2eContests();
  await login(page, seeded.judging.sponsor_login_seed);

  // 서버는 `page_size=20` 으로 페이지네이션한다. 1페이지만 그리면 21번째부터는
  // **도달할 길이 없는데**, `count` 는 전체 건수라 잘렸다는 사실조차 화면에
  // 없다. `-created_at` 정렬이라 잘리는 쪽이 오래된 것들이고, 그중 하나가
  // 「내 차례」면 이 화면이 막으려던 결과가 그대로 일어난다.
  //
  // 21건을 실제로 개최시키는 것은 이 화면과 무관한 비용이라, 서버 응답의
  // 페이지 두 장을 그대로 흉내 낸다 — 확인할 것은 화면이 잘림을 드러내고
  // 이어 붙이는가다.
  const rowAt = (index: number) => ({
    contest_id: 900000 + index,
    title: `공모전 ${index}`,
    prize: 1_000_000,
    status: "published",
    deadline_at: new Date(Date.now() + 86_400_000).toISOString(),
    judging_ends_at: null,
    submission_count: 0,
    next_action: "awaiting_submissions",
    created_at: new Date().toISOString(),
  });

  await page.route("**/api/backend/contests/mine*", (route) => {
    const url = new URL(route.request().url());
    const pageNumber = Number(url.searchParams.get("page") ?? "1");
    const start = (pageNumber - 1) * 20;
    const items = Array.from({ length: pageNumber === 1 ? 20 : 1 }, (_, i) => rowAt(start + i));
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items, count: 21 }),
    });
  });

  await page.goto("/console/contests");

  const rows = page.getByTestId("my-contests-list").locator("li");
  await expect(rows).toHaveCount(20);
  // 잘렸다는 사실이 화면에 있어야 한다.
  await expect(page.getByTestId("my-contests-load-more")).toContainText("20 / 21");

  await page.getByTestId("my-contests-load-more").click();

  // **이어 붙인다** — 갈아끼우면 앞 20개가 사라진다.
  await expect(rows).toHaveCount(21);
  await expect(page.getByTestId("my-contests-load-more")).toHaveCount(0);
});

test("세션이 없으면 렌더링 전에 로그인으로 돌아간다 — 보호된 내용이 응답에 없다", async ({
  page,
}) => {
  const response = await page.goto("/console/contests");

  expect(response?.status()).toBeLessThan(400);
  await expect(page).toHaveURL(/\/login/);
  expect(await page.content()).not.toContain("내 공모전");
});
