// 탈퇴 화면 (#100, ADR-0025) — 콘솔에서 클릭으로 닿고, 막는 것이 있으면 목록을
// 보여주고, 없으면 확인 절차를 거쳐 탈퇴가 완료되고 로그인 상태가 아니게 된다.
//
// 시임은 실행 중인 공개 앱 하나다(ADR-0017/0021). 백엔드의 실제 차단 판정
// (Contest·Payout 상태 조합)은 backend/tests/test_withdrawal.py가 HTTP로 이미
// 고정한다 — 여기서는 화면이 서버 응답을 어떻게 옮기는지만 본다. 그래서 "막힘"
// 시나리오는 백엔드를 다시 처음부터 세팅하지 않고 그 응답을 라우트로 흉내 낸다
// (appeal.spec.ts의 채점 전 404 목킹과 같은 관용구).
import { expect, test } from "@playwright/test";
import { establishDeveloperSession } from "./lib/session";

function uniqueSeed(label: string): string {
  return `wd-${label}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

async function login(page: import("@playwright/test").Page, seed: string): Promise<void> {
  await establishDeveloperSession(page, seed);
}

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
