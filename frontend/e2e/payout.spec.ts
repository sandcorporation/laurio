// 지급 화면 (#74) — 얼마가 되어 내게 오는지, 지금 무엇이 남았는지.
//
// 시임은 실행 중인 공개 앱 하나다(ADR-0017/0021). 금액 계산과 상태 전이는
// backend/tests/test_payouts.py 가 실물로 검증한다 — 여기서 확인할 것은 **화면이
// 그 값을 어떻게 구분해 보여주는가**다. 그래서 상태별 렌더링은 서버 응답을 좁게
// 갈아끼워 친다(이의 화면 스펙과 같은 방식). 소유권·미수상 같은 경계는 갈아끼우지
// 않고 실제 서버가 답하게 둔다.
import { expect, test } from "@playwright/test";

import { seedE2eContests } from "./lib/seed";
import { establishDeveloperSession } from "./lib/session";

// 로그인 **화면**은 여기서 검증 대상이 아니다(#155) — 그건 auth·oauth 스펙의 일이다.
// 여기 필요한 것은 「로그인된 상태」라는 전제뿐이라, 앱의 실제 로그인 라우트를 실제
// 백엔드에 대고 화면 없이 부른다.
async function login(page: import("@playwright/test").Page, seed: string): Promise<void> {
  await establishDeveloperSession(page, seed);
}

const AMOUNTS = {
  idempotency_key: "11111111-2222-3333-4444-555555555555",
  contest_id: 1,
  prize_amount: 1_000_000,
  platform_fee_amount: 100_000,
  withholding_tax_amount: 44_000,
  net_amount: 856_000,
  has_identity: false,
  seller_status: null,
  // 두 필드는 #57 코드리뷰 지적 8/10/12(3차)가 만든 새 신호다 — 기본값을
  // "할 일이 없다"쪽으로 둬서, 이 값을 신경 쓰지 않는 기존 테스트들이
  // 전화번호 폼이나 "실이체 실패" 문구를 뜻하지 않게 계속 보게 되는 것을
  // 막는다. 그 신호를 직접 검증하려는 테스트만 명시적으로 덮어쓴다.
  has_seller_phone: true,
  // #168 이 이메일까지 더한다 — 같은 이유로 기본값은 "이미 냈다"쪽이다.
  has_seller_email: true,
  transfer_status: "not_requested",
  created_at: new Date().toISOString(),
};

async function stubPayout(
  page: import("@playwright/test").Page,
  contestId: number,
  overrides: Record<string, unknown>,
): Promise<void> {
  await page.route(`**/api/backend/contests/${contestId}/payout`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...AMOUNTS, contest_id: contestId, ...overrides }),
    }),
  );
}

test("남의 Contest 를 직접 쳐도 금액이 새지 않는다", async ({ page }) => {
  const seeded = await seedE2eContests();
  await login(page, `e2e-payout-intruder-${Date.now()}`);

  await page.goto(`/console/payouts/${seeded.judging.id}`);

  // 서버가 403(남의 것)을 내든 404(아직 Award 되지 않음)를 내든, 여기서
  // 지켜야 할 것은 하나다 — **금액 내역이 보이지 않는다.** 어느 코드가 나오는지는
  // backend/tests/test_payouts.py 가 실물로 검증하므로 여기서 다시 고정하지
  // 않는다(시드에 Award·Handover 까지 간 Contest 가 없어 여기서는 404 다).
  await expect(page.getByTestId("payout-heading")).toBeVisible();
  await expect(page.getByTestId("payout-amounts")).toHaveCount(0);
  await expect(page.getByTestId("payout-identity-form")).toHaveCount(0);
});

// --- #168: 연락처(전화번호·이메일) 부분 제출이 낸 것을 보존한다 -----------------------
//
// 「남길 것」기준의 돈이 움직이는 곳(지급) — 이메일 공백이 만드는 조용한 정체를 닫는
// 스펙에서 가장 눈에 보이는 화면 변화다. backend/tests/test_payouts.py 가 서버 판정
// (Hold → "Developer 의 차례")을 이미 실물로 고정하므로, 여기서는 화면이 그 두 사실
// (has_seller_phone/has_seller_email)로 폼을 어떻게 그리는지만 본다.
test("연락처를 부분 제출해도 이미 낸 값은 다시 묻지 않는다", async ({ page }) => {
  const seeded = await seedE2eContests();
  await login(page, `e2e-payout-contact-${Date.now()}`);
  const contestId = seeded.judging.id;

  let phoneSubmitted = false;
  let emailSubmitted = false;

  await page.route(`**/api/backend/contests/${contestId}/payout`, (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...AMOUNTS,
        contest_id: contestId,
        status: "confirmed_seller_pending",
        seller_status: "pending",
        has_seller_phone: phoneSubmitted,
        has_seller_email: emailSubmitted,
        next_action_message:
          "지급대행사 수취인 등록에 연락처 정보가 필요합니다 — 아래에서 제출해주세요.",
      }),
    });
  });

  await page.route(
    `**/api/backend/payouts/${AMOUNTS.idempotency_key}/seller-contact`,
    (route) => {
      const body = route.request().postDataJSON() as { phone_number?: string; email?: string };
      if (body.phone_number) phoneSubmitted = true;
      if (body.email) emailSubmitted = true;
      return route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    },
  );

  await page.goto(`/console/payouts/${contestId}`);

  // 둘 다 비어 있다 — 폼이 두 입력 모두 보여준다.
  await expect(page.getByTestId("payout-seller-phone-input")).toBeVisible();
  await expect(page.getByTestId("payout-seller-email-input")).toBeVisible();

  // 전화번호만 낸다.
  await page.getByTestId("payout-seller-phone-input").fill("01012345678");
  await page.getByTestId("payout-seller-contact-submit").click();

  // 전화번호는 이미 냈다 — 재조회한 화면이 전화번호 입력을 다시 보여주지 않는다.
  // 이메일 입력은 여전히 남아 있다(부분 제출이 낸 것을 보존한다).
  await expect(page.getByTestId("payout-seller-phone-input")).toHaveCount(0);
  await expect(page.getByTestId("payout-seller-email-input")).toBeVisible();

  await page.getByTestId("payout-seller-email-input").fill("payout@example.com");
  await page.getByTestId("payout-seller-contact-submit").click();

  // 둘 다 냈다 — 폼 자체가 사라진다.
  await expect(page.getByTestId("payout-seller-contact-form")).toHaveCount(0);
});
