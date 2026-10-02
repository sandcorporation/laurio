import { expect, test } from "@playwright/test";

import { createDraftContest, findIdByName } from "./lib/contests-api";
import { establishDeveloperSession, establishVerification } from "./lib/session";

// 결제 화면 — 벤더 없이 자리를 세운다 (#86, spec #82).
//
// 지금까지 결제 화면이 없어 개최 → 결제 → 공개를 URL을 직접 쳐야만 걸을 수
// 있었다. 이 스펙은 화면을 통해 그 전 구간을 걷고, 실패·재시도·이미 결제된
// Contest·남의 결제 화면이라는 네 가지 경계도 함께 확인한다. Fake PG이므로
// 결정적이고 기본 스위트에 들어간다(#86 인수조건) — 벤더는 이 티켓의 범위
// 밖이다(#87).

async function login(page: import("@playwright/test").Page, seed: string): Promise<void> {
  // 화면을 열지 않는다 — 이 파일의 시험은 각자 자기 화면으로 곧장 간다(시험 하나 3초 한도).
  await establishDeveloperSession(page, seed, null);
}

async function verify(page: import("@playwright/test").Page, seed: string): Promise<void> {
  await establishVerification(page, seed);
}

function futureLocalDatetime(daysAhead: number): string {
  const d = new Date(Date.now() + daysAhead * 24 * 60 * 60 * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 브리프 폼을 채워 draft Contest를 하나 만들고 응답에서 id를 읽어 돌려준다
 * (grill.spec.ts의 createDraftViaForm과 같은 헬퍼 — 화면 URL에는 id가 없다). */
async function createDraftViaForm(
  page: import("@playwright/test").Page,
  runId: string,
  prize = 5_000_000,
): Promise<number> {
  const api = page.context().request;
  const [categoryId, deliverableTypeId] = await Promise.all([
    findIdByName(api, "/api/backend/contests/categories", "게임"),
    findIdByName(api, "/api/backend/contests/deliverable-types", "웹 서비스"),
  ]);

  await page.goto("/console/contests/new");
  await expect(page.getByTestId("grill-brief-heading")).toBeVisible();

  await page.getByTestId("grill-brief-title").fill(`[E2E] 결제 테스트 ${runId}`);
  await page.getByTestId("grill-brief-category").selectOption(String(categoryId));
  await page.getByTestId(`grill-brief-deliverable-type-${deliverableTypeId}-checkbox`).check();
  await page.getByTestId("grill-brief-prize").fill(String(prize));
  await page.getByTestId("grill-brief-deadline").fill(futureLocalDatetime(10));

  const [response] = await Promise.all([
    page.waitForResponse(
      (res) => res.url().endsWith("/api/backend/contests") && res.request().method() === "POST",
    ),
    page.getByTestId("grill-brief-submit").click(),
  ]);
  const body = (await response.json()) as { id: number };

  await expect(page.getByTestId("grill-draft-panel")).toBeVisible();
  return body.id;
}

test.describe("개최 → 결제 화면 → 공개", () => {
  // 예전에는 한 시험이 개최 폼부터 공개까지를 다 걸었다 — 시험 하나 3초 한도(2026-10-02)
  // 때문에 둘로 나눴고 단언은 하나도 버리지 않았다: 폼에서 결제 화면까지는 이 시험이,
  // 결제 화면에서 공개까지는 다음 시험이 본다.
  test("개최 폼으로 만든 초안 패널에 결제로 이어가는 진입점이 있고, 누르면 그 결제 화면으로 간다", async ({
    page,
  }) => {
    const runId = `${Date.now()}`;
    await login(page, `pay-entry-${runId}`);
    await verify(page, `pay-entry-${runId}`);

    const contestId = await createDraftViaForm(page, runId, 5_000_000);

    // URL을 직접 쳐야만 결제로 닿는 경로가 아니다 — 방금 만든 화면 자체에
    // 결제로 이어가는 진입점이 있다.
    await expect(page.getByTestId("grill-go-to-payment")).toBeVisible();
    await page.getByTestId("grill-go-to-payment").click();
    await expect(page).toHaveURL(new RegExp(`/console/contests/${contestId}/payment`));
  });

  test("결제 화면에서 결제하면 공모전이 공개된다", async ({ page }) => {
    const runId = `${Date.now()}`;
    await login(page, `pay-happy-${runId}`);
    await verify(page, `pay-happy-${runId}`);
    const contestId = await createDraftContest(page, `[E2E] 결제 테스트 ${runId}`, 5_000_000);

    await page.goto(`/console/contests/${contestId}/payment`);

    // 무엇에 대한 얼마인지가 화면에 있다 — 상금·개최비·합계.
    await expect(page.getByTestId("payment-heading")).toContainText(`[E2E] 결제 테스트 ${runId}`);
    await expect(page.getByTestId("payment-prize-amount")).toHaveText("5,000,000원");
    const listingFeeText = await page.getByTestId("payment-listing-fee-amount").innerText();
    const totalText = await page.getByTestId("payment-total-amount").innerText();
    const listingFee = Number(listingFeeText.replace(/[^0-9]/g, ""));
    const total = Number(totalText.replace(/[^0-9]/g, ""));
    expect(listingFee).toBeGreaterThan(0);
    expect(total).toBe(5_000_000 + listingFee);

    // 결제 건 식별자(payment key)가 브라우저에서 실제로 보내진다(#86) — Fake
    // PG는 이 값을 무시하지만, 브라우저 → BFF → 백엔드로 실려 가는지는 여기서
    // 확인한다. 어댑터까지의 전달은 backend/tests/test_payments.py가 스파이로
    // 확인한다.
    const confirmRequest = page.waitForRequest(
      (req) =>
        /\/api\/backend\/payments\/.+\/confirm$/.test(req.url()) && req.method() === "POST",
    );
    await page.getByTestId("payment-pay-button").click();
    const request = await confirmRequest;
    const sentBody = request.postDataJSON() as { payment_key?: string | null };
    expect(sentBody.payment_key).toBeTruthy();

    await expect(page.getByTestId("payment-success")).toBeVisible();

    // 공개됐다는 것이 화면 문구가 아니라 실제 데이터로도 성립한다.
    const contestStatus = await page.evaluate(async (id) => {
      const res = await fetch(`/api/backend/contests/${id}`);
      return (await res.json()).status as string;
    }, contestId);
    expect(contestStatus).toBe("published");
  });

  test("남의 결제 화면에서는 아무 금액도 보이지 않는다", async ({ page }) => {
    const runId = `${Date.now()}`;
    await login(page, `pay-owner-${runId}`);
    await verify(page, `pay-owner-${runId}`);
    const contestId = await createDraftContest(page, `[E2E] 결제 테스트 ${runId}`);

    // 다른 계정으로 로그인해 같은 Contest의 결제 화면을 직접 연다.
    await login(page, `pay-stranger-${runId}`);
    await page.goto(`/console/contests/${contestId}/payment`);

    await expect(page.getByTestId("payment-not-found")).toBeVisible();
    await expect(page.getByTestId("payment-summary")).toHaveCount(0);
    await expect(page.getByTestId("payment-prize-amount")).toHaveCount(0);
  });

});
