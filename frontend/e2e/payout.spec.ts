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

// --- #91: 폼 조건이 백엔드 안내와 어긋난다 ---------------------------------------
//
// 전화번호 폼은 `!has_seller_phone` 하나만 보고 떴다. 그런데 백엔드의 Hold 표
// (`payouts/progress.py`)가 전화번호를 요구하는 것은 Seller 가 아직 없거나 PENDING
// 일 때뿐이다 — 심사 중(under_review)이나 거절(rejected)에는 "심사가 끝나면 자동으로
// 넘어간다"·"운영자에게 문의하라"고 말한다. 화면이 시키는 대로 번호를 내면 아무 일도
// 일어나지 않는다.
