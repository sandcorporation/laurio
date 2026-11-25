import { expect, test, type Route } from "@playwright/test";

import { findIdByName } from "../lib/contests-api";
import { establishDeveloperSession, establishVerification } from "../lib/session";

// 공개 앱도 공용 `normalizeDetail` 의 422 한국어를 받는다(#1390). 라벨 맵은 넘기지 않아 문구만 나간다.
test("공모전 만들기가 422 면 한국어가 보이고 영어 원문은 없다", async ({ page }) => {
  const seed = `create422-${test.info().workerIndex}-${Date.now()}`;
  await establishDeveloperSession(page, seed, null);
  await establishVerification(page, seed);
  const api = page.context().request;
  const [categoryId, deliverableTypeId] = await Promise.all([
    findIdByName(api, "/api/backend/contests/categories", "게임"),
    findIdByName(api, "/api/backend/contests/deliverable-types", "웹 서비스"),
  ]);
  await page.route(
    (url) => url.pathname === "/api/backend/contests",
    (route: Route) =>
      route.request().method() === "POST"
        ? route.fulfill({
            status: 422,
            json: {
              detail: [
                {
                  type: "string_too_long",
                  loc: ["body", "payload", "title"],
                  msg: "String should have at most 200 characters",
                  ctx: { max_length: 200 },
                },
              ],
            },
          })
        : route.continue(),
  );
  await page.goto("/console/contests/new");
  await page.getByTestId("grill-brief-title").fill("422 확인");
  await page.getByTestId("grill-brief-category").selectOption(String(categoryId));
  await page.getByTestId(`grill-brief-deliverable-type-${deliverableTypeId}-checkbox`).check();
  await page.getByTestId("grill-brief-prize").fill("5000000");
  await page.getByTestId("grill-brief-deadline").fill("2099-01-01T00:00");

  await page.getByTestId("grill-brief-submit").click();

  await expect(page.getByTestId("grill-brief-error")).toHaveText("200자까지 쓸 수 있습니다.");
  await expect(page.getByText("String should")).toHaveCount(0);
});
