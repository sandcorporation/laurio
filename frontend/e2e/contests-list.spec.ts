import fs from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { seedE2eContests, type SeededContests } from "./lib/seed";

// FE-04(#29) — `/contests` 가 서버에서 렌더링되는지 증명한다.
//
// frontend/e2e/seam.spec.ts 상단 주석이 세운 규율 그대로: HTML 에 마크업이 있다는
// 것만으로는 "use client" 실수를 못 잡는다. 실제로 갈리는 것은 **백엔드에서 온
// 값**이다 — 그래서 아래 테스트들은 seed_e2e_contests 가 방금 DB에 심은 제목·
// 상금·마감을, 클라이언트에서 다시 요청하지 않고 받은 JS-off HTML 에서 직접
// 찾는다. 이 시드는 하드코딩 픽스처가 아니라 진짜 Django Contest 다(e2e/lib/seed.ts).
let seeded: SeededContests;

test.beforeAll(async () => {
  seeded = await seedE2eContests();
});

test("@exclusive 이 페이지에 \"use client\" 가 없다", () => {
  // AC를 코드로 직접 확인한다 — HTTP 시임만으로는 서버/클라이언트 컴포넌트
  // 여부를 구분할 수 없으므로(둘 다 초기 요청에 프리렌더된다), 여기서만 예외적으로
  // 소스를 읽는다. 렌더링 결과(백엔드 값이 JS-off HTML 에 있는지)는 아래
  // 테스트들이 별도로 증명한다 — 이 테스트는 그 증명이 우연이 아님을 보강한다.
  const source = fs.readFileSync(
    path.join(__dirname, "../app/contests/page.tsx"),
    "utf-8",
  );
  expect(source).not.toContain('"use client"');
});

test.describe("@exclusive 자바스크립트 없이", () => {
  test.use({ javaScriptEnabled: false });

  test("공모전 제목·상금·마감이 서버 렌더링된 HTML 에 들어 있다", async ({ page }) => {
    await page.goto("/contests");
    const html = await page.content();

    // 백엔드가 준 값 그대로 — 프론트가 흉내 낸 값이 아니다.
    expect(html).toContain(seeded.funded.title);
    expect(html).toContain(seeded.funded.prize.toLocaleString("ko-KR"));

    expect(html).toContain(seeded.underfunded.title);
    expect(html).toContain(seeded.underfunded.prize.toLocaleString("ko-KR"));
  });

  test("로그인 없이 접근된다", async ({ page }) => {
    const response = await page.goto("/contests");
    expect(response?.status()).toBe(200);
  });

  test("마감된 Contest 도 목록에 남는다", async ({ page }) => {
    // ADR-0014 — 마감은 결제 취소가 아니라 데모·영상이 공개되는 시점이다.
    await page.goto("/contests");
    const html = await page.content();
    expect(html).toContain(seeded.closed.title);
  });

  test("draft Contest 는 목록에 나오지 않는다", async ({ page }) => {
    await page.goto("/contests");
    const html = await page.content();
    expect(html).not.toContain(seeded.draft.title);
  });

  test("「상금미달」 배지가 최소 제안 상금 합계 미달 Contest 에만 붙는다", async ({ page }) => {
    await page.goto("/contests");
    const row = page.locator(`[data-contest-row="${seeded.underfunded.id}"]`);
    await expect(row.getByText("상금미달")).toBeVisible();

    const fundedRow = page.locator(`[data-contest-row="${seeded.funded.id}"]`);
    await expect(fundedRow.getByText("상금미달")).toHaveCount(0);
  });

  test("배지가 참가를 막지 않는다는 설명이 화면에 있다", async ({ page }) => {
    await page.goto("/contests");
    await expect(page.getByText("참가를 막지 않습니다", { exact: false })).toBeVisible();
  });
});

// `page.content()` 는 쓰지 않는다 — Next 의 `<Link>` 클릭은 클라이언트 소프트
// 내비게이션이라 문서 전체를 다시 받지 않고, 최초 로드 때 심어진 하이드레이션용
// `<script>` 태그(RSC flight 페이로드)는 클릭 이후에도 DOM 에 그대로 남는다. 그
// 안에는 필터 적용 전 문자열이 문자 그대로 박제돼 있어 `page.content()`(document
// 전체 직렬화)로 보면 필터링이 안 된 것처럼 오검출된다. `main` 안의 실제 렌더링된
// 텍스트만 보면 이 문제가 없다.
test("@exclusive Category 로 좁히면 다른 Category 의 Contest 는 사라진다", async ({ page }) => {
  // funded 와 underfunded 는 seed_e2e_contests 가 서로 다른 Category 로 심는다.
  await page.goto("/contests");
  const categoryLink = page.getByRole("link", { name: seeded.funded.category, exact: true });
  await categoryLink.click();
  await expect(page).toHaveURL(/category=\d+/);

  const rendered = await page.locator("main").innerText();
  expect(rendered).toContain(seeded.funded.title);
  expect(rendered).not.toContain(seeded.underfunded.title);
});

test("@exclusive DeliverableType 으로 좁히면 그 형태를 갖지 않은 Contest 는 사라진다", async ({ page }) => {
  // funded 는 deliverable_types 하나(웹 서비스)만, underfunded 는 웹 서비스 +
  // 모바일 앱 둘 다 갖는다(seed_e2e_contests) — funded 에는 없는
  // "모바일 앱" 으로 좁히면 funded 가 빠져야 한다.
  const mobileAppType = seeded.underfunded.deliverable_types.find(
    (name) => !seeded.funded.deliverable_types.includes(name),
  );
  expect(mobileAppType).toBeDefined();

  await page.goto("/contests");
  await page.getByRole("link", { name: mobileAppType!, exact: true }).click();
  await expect(page).toHaveURL(/deliverableType=\d+/);

  const rendered = await page.locator("main").innerText();
  expect(rendered).toContain(seeded.underfunded.title);
  expect(rendered).not.toContain(seeded.funded.title);
});

test("@exclusive 상금순 정렬이 마감 임박순과 다른 순서를 낸다", async ({ page }) => {
  await page.goto("/contests?sort=prize");
  const titles = await page.locator("[data-contest-row]").allTextContents();
  const fundedIndex = titles.findIndex((t) => t.includes(seeded.funded.title));
  const underfundedIndex = titles.findIndex((t) => t.includes(seeded.underfunded.title));

  // funded(3,000,000) 가 underfunded(1,000,000) 보다 상금이 크므로 상금순에서
  // 앞에 와야 한다.
  expect(fundedIndex).toBeGreaterThanOrEqual(0);
  expect(underfundedIndex).toBeGreaterThanOrEqual(0);
  expect(fundedIndex).toBeLessThan(underfundedIndex);
});

// PS-01 (#106, spec #105) — 참가작 수가 목록에 보이고, 백엔드가 낸 값과
// 일치한다(심고 세는 것을 같은 테스트에서 대비시킨다, #106 인수조건). 화면은
// 이 숫자를 다시 세지 않는다 — seed_e2e_contests.py 가 이미 심은 뒤 다시 세어
// 돌려준 값(seeded.funded.submission_count)을 그대로 기대값으로 쓴다.
test("@exclusive 참가작 수가 목록에 보이고 백엔드가 심은 값과 일치한다", async ({ page }) => {
  await page.goto("/contests");

  const count = page
    .locator(`[data-contest-row="${seeded.funded.id}"]`)
    .getByTestId("submission-count");
  await expect(count).toHaveText(`참가작 ${seeded.funded.submission_count}건`);
  await expect(count).toHaveAttribute(
    "data-submission-count",
    String(seeded.funded.submission_count),
  );
});

// 0도 숨기지 않는다 — "0"이라는 숫자가 아니라 "아직 참가작이 없습니다"로
// 읽힌다. 숫자와 문구가 다른 층에서 결정된다는 것이 #106 인수조건이다.
test("@exclusive 참가작이 없는 Contest 는 「아직 참가작이 없습니다」로 보인다", async ({
  page,
}) => {
  expect(seeded.underfunded.submission_count).toBe(0);

  await page.goto("/contests");

  const count = page
    .locator(`[data-contest-row="${seeded.underfunded.id}"]`)
    .getByTestId("submission-count");
  await expect(count).toHaveText("아직 참가작이 없습니다");
  await expect(count).toHaveAttribute("data-submission-count", "0");
});

test("@exclusive 마감이 임박한 Contest 가 시각적으로 구분된다", async ({ page }) => {
  // underfunded 는 2일 뒤 마감(seed_e2e_contests) — IMMINENT_DEADLINE_DAYS(3일)
  // 안쪽이라 임박 스타일(text-attention)이 붙어야 한다. funded 는 10일 뒤라 붙지
  // 않아야 한다.
  await page.goto("/contests");
  const imminentDeadline = page
    .locator(`[data-contest-row="${seeded.underfunded.id}"]`)
    .locator('[data-testid="deadline"]');
  await expect(imminentDeadline).toHaveClass(/text-attention/);

  const farDeadline = page
    .locator(`[data-contest-row="${seeded.funded.id}"]`)
    .locator('[data-testid="deadline"]');
  await expect(farDeadline).not.toHaveClass(/text-attention/);
});
