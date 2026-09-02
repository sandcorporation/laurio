// 탈퇴 화면 (#100, ADR-0025) — 콘솔에서 클릭으로 닿고, 막는 것이 있으면 목록을
// 보여주고, 없으면 확인 절차를 거쳐 탈퇴가 완료되고 로그인 상태가 아니게 된다.
//
// 시임은 실행 중인 공개 앱 하나다(ADR-0017/0021). 백엔드의 실제 차단 판정
// (Contest·Payout 상태 조합)은 backend/tests/test_withdrawal.py가 HTTP로 이미
// 고정한다 — 여기서는 화면이 서버 응답을 어떻게 옮기는지만 본다. 그래서 "막힘"
// 시나리오는 백엔드를 다시 처음부터 세팅하지 않고 그 응답을 라우트로 흉내 낸다
// (appeal.spec.ts의 채점 전 404 목킹과 같은 관용구).
import { expect, test } from "@playwright/test";

function uniqueSeed(label: string): string {
  return `wd-${label}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

async function login(page: import("@playwright/test").Page, seed: string): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("fake-login-seed").fill(seed);
  await page.getByTestId("login-kakao").click();
  await expect(page).toHaveURL(/\/console/);
}

test("콘솔에서 클릭만으로 탈퇴 화면에 닿는다", async ({ page }) => {
  await login(page, uniqueSeed("reach"));

  await page.getByTestId("app-home-withdraw-link").click();

  await expect(page).toHaveURL(/\/console\/withdraw/);
  await expect(page.getByTestId("withdraw-heading")).toBeVisible();
});

test("무엇이 사라지고 무엇이 남는지, 되돌릴 수 없다는 사실을 말한다", async ({ page }) => {
  await login(page, uniqueSeed("explain"));

  await page.goto("/console/withdraw");

  await expect(page.getByTestId("withdraw-explanation")).toContainText("실명");
  await expect(page.getByTestId("withdraw-explanation")).toContainText("공개 프로필");
  await expect(page.getByTestId("withdraw-explanation")).toContainText("이름 없이");
  await expect(page.getByTestId("withdraw-irreversible")).toContainText("되돌릴 수 없습니다");
});

test("막는 것이 있으면 목록으로 보이고, 확인 절차는 뜨지 않는다", async ({ page }) => {
  await login(page, uniqueSeed("blocked"));

  await page.route("**/api/backend/accounts/withdrawal", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        can_withdraw: false,
        blocking_reasons: ["sponsor_contest_in_progress", "developer_payout_in_progress"],
      }),
    });
  });

  await page.goto("/console/withdraw");

  await expect(page.getByTestId("withdraw-blocked")).toBeVisible();
  await expect(
    page.getByTestId("withdraw-blocking-reason-sponsor_contest_in_progress"),
  ).toContainText("Contest");
  await expect(
    page.getByTestId("withdraw-blocking-reason-developer_payout_in_progress"),
  ).toContainText("Payout");
  await expect(page.getByTestId("withdraw-confirm-section")).toHaveCount(0);
});

test("막는 것이 없으면 체크박스를 확인해야 탈퇴 버튼이 켜진다", async ({ page }) => {
  await login(page, uniqueSeed("checkbox"));

  await page.goto("/console/withdraw");

  await expect(page.getByTestId("withdraw-confirm-section")).toBeVisible();
  const submit = page.getByTestId("withdraw-submit");
  await expect(submit).toBeDisabled();

  await page.getByTestId("withdraw-ack-checkbox").check();
  await expect(submit).toBeEnabled();
});

test("탈퇴를 완료하면 로그인 화면으로 돌아가고, 그 계정으로 다시 로그인할 수 없다", async ({
  page,
}) => {
  const seed = uniqueSeed("complete");
  await login(page, seed);

  await page.goto("/console/withdraw");
  await page.getByTestId("withdraw-ack-checkbox").check();
  await page.getByTestId("withdraw-submit").click();

  await expect(page).toHaveURL(/\/login/);

  // 탈퇴한 계정으로는 다시 로그인할 수 없다 — CI가 사라져 되돌릴 수 없다는
  // 사실이 로그인 화면에서도 확인된다.
  await page.getByTestId("fake-login-seed").fill(seed);
  await page.getByTestId("login-kakao").click();

  await expect(page.getByTestId("login-error")).toBeVisible();
  await expect(page).not.toHaveURL(/\/console/);
});
