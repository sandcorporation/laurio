// 지급 화면 (#74) — 얼마가 되어 내게 오는지, 지금 무엇이 남았는지.
//
// 시임은 실행 중인 공개 앱 하나다(ADR-0017/0021). 금액 계산과 상태 전이는
// backend/tests/test_payouts.py 가 실물로 검증한다 — 여기서 확인할 것은 **화면이
// 그 값을 어떻게 구분해 보여주는가**다. 그래서 상태별 렌더링은 서버 응답을 좁게
// 갈아끼워 친다(이의 화면 스펙과 같은 방식). 소유권·미수상 같은 경계는 갈아끼우지
// 않고 실제 서버가 답하게 둔다.
import { expect, test } from "@playwright/test";

import { seedE2eContests } from "./lib/seed";

// 로그인 뒤 `/console` 도달까지 넉넉히 기다린다 — 4워커로 도는 dev 서버는 라우트를 요청받을 때
// 컴파일하므로(globalSetup 이 미리 데워도 부하가 겹치면 늦다) 기본 5초를 넘길 때가 있다. 실제로
// 이 헬퍼가 스위트 전체에서 무작위로 한 건씩 붉게 만들었다.
async function login(page: import("@playwright/test").Page, seed: string): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("fake-login-seed").fill(seed);
  await page.getByTestId("login-kakao").click();
  await expect(page).toHaveURL(/\/console/, { timeout: 15_000 });
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

test("상금 그대로가 들어오지 않는다는 것을 지급 전에 본다", async ({ page }) => {
  const seeded = seedE2eContests();
  await login(page, seeded.judging.developer_login_seed);

  const contestId = seeded.judging.id;
  await stubPayout(page, contestId, {
    status: "requested",
    next_action_message: "지급 확인 절차가 진행 중입니다. 잠시만 기다려주세요.",
  });

  await page.goto(`/console/payouts/${contestId}`);

  // 네 줄이 모두 보여야 한다 — 실수령액만 보여주면 왜 줄었는지 모르고,
  // 상금만 보여주면 지급 뒤에 설명하게 된다.
  await expect(page.getByTestId("payout-amount-prize")).toContainText("1,000,000");
  await expect(page.getByTestId("payout-amount-fee")).toContainText("100,000");
  await expect(page.getByTestId("payout-amount-withholding")).toContainText("44,000");
  await expect(page.getByTestId("payout-amount-net")).toContainText("856,000");
});

test("주민등록번호 대기와 지급대행 등록 대기를 다르게 그린다", async ({ page }) => {
  const seeded = seedE2eContests();
  await login(page, seeded.judging.developer_login_seed);
  const contestId = seeded.judging.id;

  // 「내 차례」 — 폼이 있다.
  await stubPayout(page, contestId, {
    status: "confirmed_identity_pending",
    next_action_message: "세무 신고를 위해 주민등록번호를 제출해주세요.",
  });
  await page.goto(`/console/payouts/${contestId}`);
  await expect(page.getByTestId("payout-identity-form")).toBeVisible();
  await expect(page.getByTestId("payout-waiting")).toHaveCount(0);

  // 「기다림」 — 하실 일이 없다고 말하고, 상금이 안전하다고 말한다. 실패가
  // 아니다(ADR-0020). 두 대기가 같은 회색 문장이면 자기 차례인 걸 모른다.
  await page.unrouteAll();
  await stubPayout(page, contestId, {
    status: "confirmed_seller_pending",
    has_identity: true,
    seller_status: "under_review",
    next_action_message: "지급대행사 심사가 진행 중입니다.",
  });
  await page.goto(`/console/payouts/${contestId}`);
  await expect(page.getByTestId("payout-waiting")).toContainText("하실 일은 없습니다");
  await expect(page.getByTestId("payout-identity-form")).toHaveCount(0);
});

test("지급대행사가 별도 인증 문자를 보낸다고 미리 말한다", async ({ page }) => {
  const seeded = seedE2eContests();
  await login(page, seeded.judging.developer_login_seed);
  const contestId = seeded.judging.id;

  await stubPayout(page, contestId, {
    status: "confirmed_identity_pending",
    next_action_message: "세무 신고를 위해 주민등록번호를 제출해주세요.",
  });

  await page.goto(`/console/payouts/${contestId}`);

  // 본인확인은 이미 포트원으로 했다 — 예고 없는 두 번째 문자는 피싱으로 읽힌다.
  await expect(page.getByTestId("payout-sms-notice").first()).toContainText("별도의 본인확인 문자");
});

test("주민등록번호는 화면에 남지 않는다 — 제출 뒤 입력칸이 비고 마스킹된다", async ({
  page,
}) => {
  const seeded = seedE2eContests();
  await login(page, seeded.judging.developer_login_seed);
  const contestId = seeded.judging.id;

  await stubPayout(page, contestId, {
    status: "confirmed_identity_pending",
    next_action_message: "세무 신고를 위해 주민등록번호를 제출해주세요.",
  });
  // 제출은 실패시킨다 — **실패했을 때야말로** 남기고 싶은 유혹이 큰 자리다.
  await page.route(`**/api/backend/payouts/*/identity`, (route) =>
    route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({ detail: "지급이 확정된 뒤에만 신원 정보를 제출할 수 있습니다." }),
    }),
  );

  await page.goto(`/console/payouts/${contestId}`);
  const input = page.getByTestId("payout-rrn-input");
  // 어깨너머로 읽히지 않는다.
  await expect(input).toHaveAttribute("type", "password");

  await input.fill("9001011234567");
  await page.getByTestId("payout-identity-submit").click();

  await expect(page.getByTestId("payout-identity-error")).toBeVisible();
  await expect(input).toHaveValue("");
  expect(await page.content()).not.toContain("9001011234567");
});

test("Seller 등록이 거절돼도 상금이 남아 있다고 말하고 재시도를 준다", async ({ page }) => {
  const seeded = seedE2eContests();
  await login(page, seeded.judging.developer_login_seed);
  const contestId = seeded.judging.id;

  await stubPayout(page, contestId, {
    status: "confirmed_seller_pending",
    has_identity: true,
    seller_status: "rejected",
    next_action_message: "지급대행사 수취인 등록이 거절되었습니다.",
  });

  await page.goto(`/console/payouts/${contestId}`);

  // 거절은 실패가 아니다 — 돈은 원장에 남아 있다(ADR-0020). 사람이 고객센터를
  // 거쳐야 하면 "상금이 사라진 것 같은 시간"만 길어진다.
  await expect(page.getByTestId("payout-seller-retry-rejected")).toContainText("그대로 남아 있습니다");
  await expect(page.getByTestId("payout-seller-retry")).toBeVisible();
});

test("실이체 자체가 거절되면 등록 거절과 다른 문구로 재시도를 준다", async ({ page }) => {
  // #57 코드리뷰 지적 11(3차) — Seller 등록은 끝났는데(READY) 실이체 자체가
  // 거절된 경우, "수취인 등록이 거절되었습니다"라고 말하면 실제 원인과
  // 어긋난다.
  const seeded = seedE2eContests();
  await login(page, seeded.judging.developer_login_seed);
  const contestId = seeded.judging.id;

  await stubPayout(page, contestId, {
    status: "confirmed_seller_pending",
    has_identity: true,
    seller_status: "partially_approved",
    transfer_status: "failed",
    next_action_message: "지급대행사 등록은 끝났지만 실제 이체가 거절되었습니다.",
  });

  await page.goto(`/console/payouts/${contestId}`);

  await expect(page.getByTestId("payout-seller-retry-transfer")).toContainText("실제 이체가 거절");
  await expect(page.getByTestId("payout-seller-retry-transfer")).not.toContainText(
    "수취인 등록이 거절",
  );
  await expect(page.getByTestId("payout-seller-retry")).toBeVisible();
  // "하실 일은 없습니다"와 재시도 버튼이 함께 뜨면 모순이다(코드리뷰 지적 10).
  await expect(page.getByText("하실 일은 없습니다")).toHaveCount(0);
});

test("수상하지 않은 행에는 지급 링크 자체가 없다", async ({ page }) => {
  const seeded = seedE2eContests();
  await login(page, seeded.judging.developer_login_seed);

  await page.goto("/console/participation");
  const rows = page.getByTestId("participation-list").locator("li");
  await expect(rows.first()).toBeVisible();

  // 심사 시드는 아직 지급 단계가 아니다. 링크를 걸어 두면 「지급 요청」 버튼이
  // 보이고, 눌러 봐야 서버가 거절한다 — 화면이 시킨 대로 했는데 거절당하는
  // 그 모양이다.
  await expect(rows.first().getByTestId(/participation-row-\d+-payout/)).toHaveCount(0);
});

test("남의 Contest 를 직접 쳐도 금액이 새지 않는다", async ({ page }) => {
  const seeded = seedE2eContests();
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

test("세션이 없으면 렌더링 전에 로그인으로 돌아간다", async ({ page }) => {
  const response = await page.goto("/console/payouts/1");

  expect(response?.status()).toBeLessThan(400);
  await expect(page).toHaveURL(/\/login/);
  expect(await page.content()).not.toContain("상금 지급");
});

// --- #91: 폼 조건이 백엔드 안내와 어긋난다 ---------------------------------------
//
// 전화번호 폼은 `!has_seller_phone` 하나만 보고 떴다. 그런데 백엔드의 Hold 표
// (`payouts/progress.py`)가 전화번호를 요구하는 것은 Seller 가 아직 없거나 PENDING
// 일 때뿐이다 — 심사 중(under_review)이나 거절(rejected)에는 "심사가 끝나면 자동으로
// 넘어간다"·"운영자에게 문의하라"고 말한다. 화면이 시키는 대로 번호를 내면 아무 일도
// 일어나지 않는다.

test("심사 중에는 전화번호를 요구하지 않는다 — 백엔드 안내와 같은 것을 말한다", async ({
  page,
}) => {
  const seeded = seedE2eContests();
  await login(page, seeded.judging.developer_login_seed);
  const contestId = seeded.judging.id;

  await stubPayout(page, contestId, {
    status: "confirmed_seller_pending",
    has_identity: true,
    has_seller_phone: false,
    seller_status: "under_review",
    next_action_message:
      "지급대행사 심사가 진행 중입니다(주간 지급 한도 초과 또는 추가 확인 요청) — 상금은 안전하게 보관되어 있으며 심사가 끝나면 자동으로 다음 단계로 넘어갑니다.",
  });
  await page.goto(`/console/payouts/${contestId}`);

  await expect(page.getByTestId("payout-next-action-message")).toContainText("심사가 끝나면");
  await expect(page.getByTestId("payout-seller-phone-form")).toHaveCount(0);
});

test("등록이 거절된 상태에서도 전화번호를 요구하지 않는다 — 할 일은 재시도다", async ({
  page,
}) => {
  const seeded = seedE2eContests();
  await login(page, seeded.judging.developer_login_seed);
  const contestId = seeded.judging.id;

  await stubPayout(page, contestId, {
    status: "confirmed_seller_pending",
    has_identity: true,
    has_seller_phone: false,
    seller_status: "rejected",
    next_action_message:
      "지급대행사 수취인 등록이 거절되었습니다. 상금은 원장에 그대로 남아 있습니다 — 운영자에게 문의해주세요.",
  });
  await page.goto(`/console/payouts/${contestId}`);

  // 먼저 이 상태에서 **있어야 할 것**이 그려질 때까지 기다린다 — 곧바로
  // toHaveCount(0)부터 치면 아직 렌더 전인 순간에 통과해버린다(이 저장소가
  // 겪은 거짓 성공).
  await expect(page.getByTestId("payout-seller-retry-rejected")).toBeVisible();
  await expect(page.getByTestId("payout-seller-phone-form")).toHaveCount(0);
});

test("아직 등록 전이면 전화번호 폼은 그대로 뜬다 — 이 경로를 막지 않았다", async ({ page }) => {
  const seeded = seedE2eContests();
  await login(page, seeded.judging.developer_login_seed);
  const contestId = seeded.judging.id;

  await stubPayout(page, contestId, {
    status: "confirmed_seller_pending",
    has_identity: true,
    has_seller_phone: false,
    seller_status: null,
    next_action_message: "지급대행사 수취인 등록에 전화번호가 필요합니다 — 아래에서 제출해주세요.",
  });
  await page.goto(`/console/payouts/${contestId}`);
  await expect(page.getByTestId("payout-seller-phone-form")).toBeVisible();

  // 등록은 접수됐지만 아직 PENDING 인 경우도 같다 — 벤더가 아직 전화번호를 못 받았다.
  await page.unrouteAll();
  await stubPayout(page, contestId, {
    status: "confirmed_seller_pending",
    has_identity: true,
    has_seller_phone: false,
    seller_status: "pending",
    next_action_message: "지급대행사 수취인 등록에 전화번호가 필요합니다 — 아래에서 제출해주세요.",
  });
  await page.goto(`/console/payouts/${contestId}`);
  await expect(page.getByTestId("payout-seller-phone-form")).toBeVisible();
});
