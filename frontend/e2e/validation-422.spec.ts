// 요청 검증 422 가 화면을 죽이지 않는다 (#147, #122).
//
// django-ninja 의 요청 검증 실패는 `detail` 이 **오류 객체 배열**이다
// (`[{"type": ..., "loc": ["body", "payload", "field"], "msg": "..."}]`). 그 값을 그대로 React 자식으로
// 렌더하면 「Objects are not valid as a React child」로 화면 전체가 죽는다 — 운영자 앱이 #69 에서
// 겪고 `normalizeDetail` 을 뒀지만 공개 앱에는 그 방어가 없었고, `detail` 을 그대로 문구로 쓰는
// 자리가 스무 곳이었다(#122 가 「잠복 결함」으로 지목한 것). 지금은 `@laurio/bff-client` 가 모든
// 실패를 문자열 하나로 좁힌다.
//
// 이 스펙은 그 자리를 닫은 증거다. 서버 응답을 ninja 가 실제로 내는 모양 그대로 갈아끼워 —
// 화면에서는 그 형식을 만들 수 없다(입력칸이 형식을 미리 강제한다) — 화면이 살아 있고 사람이 읽을
// 문구가 뜨는지 본다.
import { expect, test } from "@playwright/test";

import { seedE2eContests } from "./lib/seed";

/** ninja 요청 검증 422 의 실제 본문 모양. */
const NINJA_VALIDATION_BODY = {
  detail: [
    {
      type: "string_pattern_mismatch",
      loc: ["body", "payload", "resident_registration_number"],
      msg: "String should match pattern '^\\d{13}$'",
      ctx: { pattern: "^\\d{13}$" },
    },
  ],
};

async function login(page: import("@playwright/test").Page, seed: string): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("fake-login-seed").fill(seed);
  await page.getByTestId("login-kakao").click();
  await expect(page).toHaveURL(/\/console/, { timeout: 15_000 });
}

test("요청 검증 422(배열 detail)에도 화면이 살아 있고 이유가 보인다", async ({ page }) => {
  const seeded = await seedE2eContests();
  await login(page, seeded.judging.developer_login_seed);
  const contestId = seeded.judging.id;

  await page.route(`**/api/backend/contests/${contestId}/payout`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        idempotency_key: "22222222-3333-4444-5555-666666666666",
        contest_id: contestId,
        prize_amount: 1_000_000,
        platform_fee_amount: 100_000,
        withholding_tax_amount: 44_000,
        net_amount: 856_000,
        has_identity: false,
        seller_status: null,
        has_seller_phone: true,
        transfer_status: "not_requested",
        status: "confirmed_identity_pending",
        next_action_message: "세무 신고를 위해 주민등록번호를 제출해주세요.",
        created_at: new Date().toISOString(),
      }),
    }),
  );
  await page.route("**/api/backend/payouts/*/identity", (route) =>
    route.fulfill({
      status: 422,
      contentType: "application/json",
      body: JSON.stringify(NINJA_VALIDATION_BODY),
    }),
  );

  const crashes: string[] = [];
  page.on("pageerror", (error) => crashes.push(error.message));

  await page.goto(`/console/payouts/${contestId}`);
  await page.getByTestId("payout-rrn-input").fill("9001011234567");
  await page.getByTestId("payout-identity-submit").click();

  // 1) 사람이 읽을 문구가 뜬다 — 배열이 아니라 서버가 말한 이유다.
  const error = page.getByTestId("payout-identity-error");
  await expect(error).toBeVisible();
  await expect(error).toContainText("resident_registration_number");
  await expect(error).toContainText("pattern");

  // 2) 화면이 죽지 않았다 — 폼도 금액도 그대로 있고, React 가 렌더 중 던지지 않았다.
  await expect(page.getByTestId("payout-identity-form")).toBeVisible();
  await expect(page.getByTestId("payout-amounts")).toBeVisible();
  expect(crashes.filter((message) => message.includes("valid as a React child"))).toEqual([]);
});
