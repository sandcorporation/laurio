import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { E2E_OPERATOR_PASSWORD, seedE2eOperator } from "../lib/seed-operator";
import { establishOperatorSession } from "../lib/session";

// 운영자 앱 11(#69) — Operator 계정 관리(ADR-0018).
//
// 「돈을 움직일 수 있다」(is_staff)와 「돈을 움직일 권한을 나눠줄 수 있다」
// (is_superuser)는 무게가 다르다(#45) — 이 화면은 상위 등급 전용이고, 일반
// Operator에게는 빈 목록이 아니라 "등급이 필요하다"고 말해야 한다.
//
// 시임 규약(ADR-0021)을 그대로 따른다 — 렌더링·클릭은 `page`로 친다. 상태
// 변화는 라벨이 아니라 효과로 증명한다(비활성화 뒤 실제로 로그인이 안 되고,
// 재활성화 뒤 다시 된다) — 트랩 노트가 지적하는 "라벨만 확인하는 단언"을 피한다.

async function loginAsOperator(page: Page, username: string, password = E2E_OPERATOR_PASSWORD): Promise<void> {
  await establishOperatorSession(page, username, password);
}

async function loginAndExpectHome(page: Page, username: string, password = E2E_OPERATOR_PASSWORD): Promise<void> {
  await loginAsOperator(page, username, password);
  await expect(page.getByTestId("operator-home-heading")).toBeVisible();
}

/** 로그아웃 — 홈이 아닌 화면(`/operators`)에도 로그아웃 버튼이 없으므로, 홈의
 * 버튼을 찾아 클릭하는 대신 로그아웃 BFF를 직접 불러 세션을 끊는다. 이 BFF도
 * 다른 변경 요청과 같은 Origin 검증을 거친다(app/api/auth/logout/route.ts) —
 * 브라우저 fetch와 달리 page.request는 Origin을 자동으로 싣지 않아 직접
 * 붙인다. */
async function logout(page: Page): Promise<void> {
  const origin = new URL(page.url()).origin;
  await page.request.post("/api/auth/logout", { headers: { origin } });
  await page.context().clearCookies();
}

/** 로그인 실패 — 계정이 존재하지 않는 것과 같은 하나의 문구로 답한다
 * (accounts/operator_api.py의 _LOGIN_FAILED, 비활성 계정도 여기 포함된다). */
async function expectLoginRefused(page: Page, username: string, password = E2E_OPERATOR_PASSWORD): Promise<void> {
  // **여기만 로그인 화면을 실제로 걷는다**(#155) — 확인하려는 것이 「거절이 화면에
  // 어떻게 보이는가」이기 때문이다. 성공 전제를 만들 때 쓰는 API 경로로 부르면 예외가
  // 날 뿐이고, 이 테스트가 묻는 질문(문구가 뜨는가)은 사라진다.
  await page.goto("/login");
  await page.getByTestId("login-username").fill(username);
  await page.getByTestId("login-password").fill(password);
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("login-error")).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
}

async function openOperatorsPage(page: Page): Promise<void> {
  await page.goto("/operators");
}

test.describe("목록 — 아이디·등급·활성 여부(#69)", () => {
});

test.describe("생성 — 실제로 로그인되는 계정이 만들어진다(#69)", () => {
});

test.describe("생성 실패 — 서로 다른 이유는 서로 다른 메시지다(#69)", () => {
});

test.describe("빈 입력 — 요청 검증 오류가 화면을 죽이지 않는다(#69)", () => {
});

test.describe("비활성화 — 효과로 증명한다(#69)", () => {
});

test.describe("마지막 상위 등급 계정(#69)", () => {
});

test.describe("일반 Operator — 403은 빈 목록이 아니다(#69)", () => {
  test("일반 Operator가 이 화면을 열면 등급이 필요하다는 취지가 보이고, 빈 목록도 깨진 화면도 아니다", async ({
    page,
  }) => {
    const ordinary = await seedE2eOperator({ username: `e2e-op-mgmt-forbidden-${Date.now()}` });

    await loginAndExpectHome(page, ordinary.username);
    await expect(page.getByTestId("operator-home-grade")).toContainText("일반 등급");

    await openOperatorsPage(page);

    await expect(page.getByTestId("operators-forbidden")).toBeVisible();
    await expect(page.getByTestId("operators-forbidden")).toContainText("등급");

    // 빈 목록도, 깨진 화면도 아니다 — 셋은 서로 다른 상태다.
    await expect(page.getByTestId("operators-table")).toHaveCount(0);
    await expect(page.getByTestId("operators-error")).toHaveCount(0);
  });
});

test.describe("세션 없이 열면 렌더링 전에 로그인으로 돌아간다(#69)", () => {
});

test.describe("홈에서 실제로 눌러 들어가는 경로(#69)", () => {
  // 코드리뷰 지적 — 이 화면으로 가는 링크가 앱 어디에도 없어서 URL을 직접
  // 쳐야만 들어갈 수 있었다. e2e가 전부 page.goto("/operators")였던 탓에
  // 그 사실이 가려져 있었다 — 그래서 여기서는 반드시 클릭으로 도달한다.
});
