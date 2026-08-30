import { expect, test } from "@playwright/test";

import { seedE2eContests, type SeededBulk, type SeededContests } from "./lib/seed";

// #39 — 목록의 필터·정렬·페이지를 백엔드가 처리한다.
//
// 이 스펙이 재현하는 실패는 구체적이다. FE-04(#29) 시절 프론트는 `page_size=200`
// 으로 목록 전체를 한 번에 받아 서버 컴포넌트 안에서 직접 걸렀다. 그런데 ninja 는
// 요청한 page_size 를 `NINJA_MAX_PER_PAGE_SIZE`(기본 100)로 잘라내므로 실제 천장은
// 100 이었고, 공개 Contest 가 그보다 많아지면 뒤쪽이 목록에서 **그냥 사라졌다** —
// 예외도 빈 화면도 아니라 없는 것처럼 보였다. 공개 표면에서 가장 나쁜 실패다.
//
// 그래서 그 천장을 실제로 넘겨(120건) 확인한다. 전용 Category 에 심으므로 다른
// 스펙이 만든 Contest 와 섞이지 않는다.
const BULK = 120;

let seeded: SeededContests;
let bulk: SeededBulk;

test.beforeAll(() => {
  seeded = seedE2eContests({ bulk: BULK });
  expect(seeded.bulk, "--bulk 로 심은 대량 Contest 가 시드 출력에 없다").toBeDefined();
  bulk = seeded.bulk!;
});

function bulkUrl(extra: Record<string, string | number> = {}): string {
  const params = new URLSearchParams({ category: String(bulk.category_id) });
  for (const [key, value] of Object.entries(extra)) params.set(key, String(value));
  return `/contests?${params.toString()}`;
}

type Page = import("@playwright/test").Page;

/** 목록이 실제로 그려질 때까지 기다린다. 새 문서를 받는 모든 지점에서 먼저 부른다. */
async function waitForList(page: Page): Promise<void> {
  await page.getByTestId("contest-count").waitFor();
}

/** 「다음」을 눌러 다음 페이지 문서를 받고, 그려질 때까지 기다린다. */
async function goToNextPage(page: Page): Promise<void> {
  await page.getByTestId("page-next").click();
  await waitForList(page);
}

// **열거 전에 반드시 기다린다.** `locator.all()` 과 `count()` 는 자동 대기를 하지
// 않는 API 라(Playwright 문서), 링크를 눌러 문서가 교체되는 중에 부르면 0건을
// 돌려준다. 그러면 6페이지를 다 돌고도 수집된 건 첫 20건뿐인 채로 "누락이 없다"를
// 검증하려던 테스트가 오히려 조용히 아무것도 검증하지 않게 된다 — 실제로 이
// 스위트에서 간헐적으로 그렇게 깨졌다(3회 중 1회).
//
// `evaluateAll` 도 쓰지 않는다 — `javaScriptEnabled: false` 에서 문서를 새로 받고
// 나면 빈 배열이 온다(직접 확인했다).
async function rowIdsOnPage(page: Page): Promise<string[]> {
  await waitForList(page);
  const rows = await page.locator("[data-contest-row]").all();
  return Promise.all(
    rows.map(async (row) => (await row.getAttribute("data-contest-row")) ?? ""),
  );
}

// JS 를 끈 상태로 도는 것 자체가 SSR 증명이다(ADR-0015) — 페이지를 넘기는 링크도
// 전부 진짜 내비게이션이라, 필터·정렬·페이지가 서버에서 적용된 HTML 로 온다.
test.describe("자바스크립트 없이", () => {
  test.use({ javaScriptEnabled: false });

  test("전체 건수는 이 페이지에 실린 수가 아니라 필터가 걸린 전체 건수다", async ({ page }) => {
    await page.goto(bulkUrl());

    await expect(page.getByTestId("contest-count")).toHaveText(String(BULK));
    await expect(page.getByTestId("contest-pagination")).toBeVisible();

    // 한 페이지에 전부 실렸다면 페이지네이션을 검증할 수 없다 — 이 스펙의 전제가
    // 무너졌다는 뜻이므로 여기서 잡는다.
    const onFirstPage = await rowIdsOnPage(page);
    expect(onFirstPage.length).toBeGreaterThan(0);
    expect(onFirstPage.length).toBeLessThan(BULK);
  });

  test("상금순 첫 페이지에는 최고 상금이 오고 최저 상금은 오지 않는다", async ({ page }) => {
    await page.goto(bulkUrl({ sort: "prize" }));
    const rendered = await page.locator("main").innerText();

    expect(rendered).toContain(bulk.highest_prize_title);
    expect(rendered).not.toContain(bulk.lowest_prize_title);
  });

  test("「다음」을 끝까지 따라가면 예전 구조가 조용히 잃던 항목에 닿는다", async ({ page }) => {
    await page.goto(bulkUrl({ sort: "prize" }));

    // 페이지 크기를 테스트가 다시 계산하지 않는다 — 화면이 주는 「다음」 링크만
    // 따라간다. 그래야 페이지 크기를 바꿔도 이 테스트가 그대로 유효하다.
    await waitForList(page);
    let hops = 0;
    while ((await page.getByTestId("page-next").count()) > 0) {
      await goToNextPage(page);
      hops += 1;
      expect(hops, "「다음」이 끝나지 않는다 — 페이지네이션이 순환한다").toBeLessThan(30);
    }

    expect(hops).toBeGreaterThan(0);
    const rendered = await page.locator("main").innerText();
    expect(rendered).toContain(bulk.lowest_prize_title);
  });

  test("모든 페이지를 모으면 중복도 누락도 없다", async ({ page }) => {
    await page.goto(bulkUrl({ sort: "prize" }));

    const seen: string[] = [];
    for (let hops = 0; hops < 30; hops += 1) {
      seen.push(...(await rowIdsOnPage(page)));
      if ((await page.getByTestId("page-next").count()) === 0) break;
      await goToNextPage(page);
    }

    expect(seen.length).toBe(BULK);
    expect(new Set(seen).size, "같은 Contest 가 두 페이지에 걸쳐 나왔다").toBe(BULK);
  });

  test("범위를 벗어난 page 는 마지막 페이지로 정정된다", async ({ page }) => {
    // 그냥 두면 「전체 120」이라고 써놓고 바로 아래에 "조건에 맞는 공모전이
    // 없습니다" 가 뜬다 — 있는데 없다고 말하는 화면이다.
    await page.goto(bulkUrl({ sort: "prize", page: 999999 }));

    await expect(page).not.toHaveURL(/page=999999/);
    await expect(page.getByTestId("contest-count")).toHaveText(String(BULK));
    expect((await rowIdsOnPage(page)).length).toBeGreaterThan(0);

    // 마지막 페이지이므로 「다음」이 없고, 상금순의 꼬리가 여기 있다.
    await expect(page.getByTestId("page-next")).toHaveCount(0);
    expect(await page.locator("main").innerText()).toContain(bulk.lowest_prize_title);
  });

  test("페이지를 넘겨도 필터와 정렬이 유지된다", async ({ page }) => {
    await page.goto(bulkUrl({ sort: "prize" }));
    await goToNextPage(page);

    await expect(page).toHaveURL(/category=\d+/);
    await expect(page).toHaveURL(/sort=prize/);
    await expect(page.getByTestId("contest-count")).toHaveText(String(BULK));
  });
});

test("필터를 바꾸면 페이지가 1 로 돌아간다", async ({ page }) => {
  // 3페이지에서 카테고리를 좁혔는데 페이지가 그대로면, 결과가 1페이지밖에 없을 때
  // "조건에 맞는 공모전이 없습니다" 가 뜬다 — 있는데 없다고 말하는 화면이다.
  await page.goto(bulkUrl({ sort: "prize", page: 3 }));
  await expect(page).toHaveURL(/page=3/);

  await page.getByRole("link", { name: seeded.funded.category, exact: true }).click();

  await expect(page).toHaveURL(/category=\d+/);
  await expect(page).not.toHaveURL(/page=/);
  const rendered = await page.locator("main").innerText();
  expect(rendered).toContain(seeded.funded.title);
});
