import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { E2E_OPERATOR_PASSWORD, seedE2eOperator } from "../lib/seed-operator";

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
  await page.goto("/login");
  await page.getByTestId("login-username").fill(username);
  await page.getByTestId("login-password").fill(password);
  await page.getByTestId("login-submit").click();
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
  await loginAsOperator(page, username, password);
  await expect(page.getByTestId("login-error")).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
}

async function openOperatorsPage(page: Page): Promise<void> {
  await page.goto("/operators");
}

test.describe("목록 — 아이디·등급·활성 여부(#69)", () => {
  test("상위 등급으로 로그인하면 Operator 목록이 아이디·등급·활성 여부와 함께 보인다", async ({
    page,
  }) => {
    const superuser = seedE2eOperator({
      username: `e2e-op-mgmt-list-super-${Date.now()}`,
      superuser: true,
    });
    const ordinary = seedE2eOperator({ username: `e2e-op-mgmt-list-ordinary-${Date.now()}` });

    await loginAndExpectHome(page, superuser.username);
    await openOperatorsPage(page);

    await expect(page.getByTestId("operators-heading")).toBeVisible();
    await expect(page.getByTestId("operators-table")).toBeVisible();

    const superRow = page.getByTestId(`operator-row-${superuser.id}`);
    await expect(superRow.getByTestId(`operator-row-${superuser.id}-username`)).toHaveText(
      superuser.username,
    );
    await expect(superRow.getByTestId(`operator-row-${superuser.id}-grade`)).toHaveText("상위 등급");
    await expect(superRow.getByTestId(`operator-row-${superuser.id}-active`)).toHaveText("활성");

    const ordinaryRow = page.getByTestId(`operator-row-${ordinary.id}`);
    await expect(ordinaryRow.getByTestId(`operator-row-${ordinary.id}-username`)).toHaveText(
      ordinary.username,
    );
    await expect(ordinaryRow.getByTestId(`operator-row-${ordinary.id}-grade`)).toHaveText("일반 등급");
    await expect(ordinaryRow.getByTestId(`operator-row-${ordinary.id}-active`)).toHaveText("활성");
  });
});

test.describe("생성 — 실제로 로그인되는 계정이 만들어진다(#69)", () => {
  test("새 Operator를 만들 수 있고, 만들어진 계정으로 실제로 로그인된다", async ({ page }) => {
    const superuser = seedE2eOperator({
      username: `e2e-op-mgmt-create-super-${Date.now()}`,
      superuser: true,
    });
    const newUsername = `e2e-op-mgmt-created-${Date.now()}`;
    const newPassword = "a-strong-unusual-password-9134";

    await loginAndExpectHome(page, superuser.username);
    await openOperatorsPage(page);

    await page.getByTestId("create-operator-username").fill(newUsername);
    await page.getByTestId("create-operator-password").fill(newPassword);
    await page.getByTestId("create-operator-submit").click();

    // 목록이 스스로 새로고침되어 방금 만든 계정을 보여준다.
    const newRow = page.locator(`tr[data-testid^="operator-row-"]`).filter({ hasText: newUsername });
    await expect(newRow).toBeVisible();
    await expect(page.getByTestId("create-operator-error")).toHaveCount(0);

    // 효과를 증명한다 — 라벨이 아니라 실제 로그인 성공으로.
    await loginAndExpectHome(page, newUsername, newPassword);
  });
});

test.describe("생성 실패 — 서로 다른 이유는 서로 다른 메시지다(#69)", () => {
  test("약한 비밀번호와 중복 아이디가 서로 다른 메시지로 거절된다", async ({ page }) => {
    const superuser = seedE2eOperator({
      username: `e2e-op-mgmt-distinct-super-${Date.now()}`,
      superuser: true,
    });
    const existing = seedE2eOperator({ username: `e2e-op-mgmt-existing-${Date.now()}` });

    await loginAndExpectHome(page, superuser.username);
    await openOperatorsPage(page);

    // 약한 비밀번호.
    await page.getByTestId("create-operator-username").fill(`e2e-op-mgmt-weakpw-${Date.now()}`);
    await page.getByTestId("create-operator-password").fill("123");
    await page.getByTestId("create-operator-submit").click();
    await expect(page.getByTestId("create-operator-error")).toBeVisible();
    const weakPasswordMessage = await page.getByTestId("create-operator-error").textContent();

    // 중복 아이디 — 이미 존재하는 계정의 이름을 그대로 쓴다.
    await page.getByTestId("create-operator-username").fill(existing.username);
    await page.getByTestId("create-operator-password").fill("a-strong-unusual-password-9134");
    await page.getByTestId("create-operator-submit").click();
    await expect(page.getByTestId("create-operator-error")).toBeVisible();
    const duplicateMessage = await page.getByTestId("create-operator-error").textContent();

    expect(weakPasswordMessage).toBeTruthy();
    expect(duplicateMessage).toBeTruthy();
    expect(weakPasswordMessage).not.toBe(duplicateMessage);

    // 둘 다 "생성 실패"라는 뭉뚱그린 문구가 아니다 — 각자 무엇이 문제인지를 담는다.
    expect(weakPasswordMessage).not.toContain("생성 실패");
    expect(duplicateMessage).not.toContain("생성 실패");
  });
});

test.describe("비활성화 — 효과로 증명한다(#69)", () => {
  test("Operator를 비활성화하면 그 계정으로 더 이상 로그인되지 않는다", async ({ page }) => {
    const superuser = seedE2eOperator({
      username: `e2e-op-mgmt-deactivate-super-${Date.now()}`,
      superuser: true,
    });
    const target = seedE2eOperator({ username: `e2e-op-mgmt-deactivate-target-${Date.now()}` });

    // 비활성화 전에는 실제로 로그인이 된다는 것부터 확인한다 — 이후의 "안 된다"가
    // 애초에 안 되던 것이 아니라 비활성화의 효과라는 것을 보장한다.
    await loginAndExpectHome(page, target.username);
    await page.getByTestId("logout-button").click();
    await expect(page).toHaveURL(/\/login/);

    await loginAndExpectHome(page, superuser.username);
    await openOperatorsPage(page);

    const row = page.getByTestId(`operator-row-${target.id}`);
    await row.getByTestId(`operator-row-${target.id}-deactivate`).click();
    await expect(row.getByTestId(`operator-row-${target.id}-active`)).toHaveText("비활성");
    await expect(row.getByTestId(`operator-row-${target.id}-reactivate`)).toBeVisible();

    await logout(page);
    await expectLoginRefused(page, target.username);
  });

  test("재활성화하면 다시 로그인된다", async ({ page }) => {
    const superuser = seedE2eOperator({
      username: `e2e-op-mgmt-reactivate-super-${Date.now()}`,
      superuser: true,
    });
    const target = seedE2eOperator({ username: `e2e-op-mgmt-reactivate-target-${Date.now()}` });

    await loginAndExpectHome(page, superuser.username);
    await openOperatorsPage(page);

    const row = page.getByTestId(`operator-row-${target.id}`);
    await row.getByTestId(`operator-row-${target.id}-deactivate`).click();
    await expect(row.getByTestId(`operator-row-${target.id}-active`)).toHaveText("비활성");

    await logout(page);
    await expectLoginRefused(page, target.username);

    await loginAndExpectHome(page, superuser.username);
    await openOperatorsPage(page);
    const rowAgain = page.getByTestId(`operator-row-${target.id}`);
    await rowAgain.getByTestId(`operator-row-${target.id}-reactivate`).click();
    await expect(rowAgain.getByTestId(`operator-row-${target.id}-active`)).toHaveText("활성");

    await logout(page);
    await loginAndExpectHome(page, target.username);
  });
});

test.describe("마지막 상위 등급 계정(#69)", () => {
  test("마지막 상위 등급 계정의 비활성화가 거절되고, 화면이 그 이유를 말한다", async ({ page }) => {
    const superuser = seedE2eOperator({
      username: `e2e-op-mgmt-last-super-${Date.now()}`,
      superuser: true,
    });

    await loginAndExpectHome(page, superuser.username);

    // 이 BFF의 변경 요청은 Origin 검증을 거친다(packages/bff-shared/src/origin.ts)
    // — 브라우저의 fetch()는 이 헤더를 자동으로 싣지만 page.request는 API
    // 테스트 클라이언트라 싣지 않으므로, 아래 정리 단계에서 직접 붙여야 한다.
    const origin = new URL(page.url()).origin;

    // 다른 활성 상위 등급 계정이 남아 있으면 "마지막"이 아니게 되어 이 테스트가
    // 무엇도 증명하지 못한다 — 이 컴포즈 스택 안에서 자기 자신 말고 남은 활성
    // superuser를 전부 비활성화해 정말로 "마지막 하나"인 상태를 만든다. 백엔드
    // API를 페이지의 세션 쿠키로 직접 호출한다(같은 브라우저 컨텍스트를 공유하는
    // page.request이므로 쿠키가 자동으로 실린다).
    const listRes = await page.request.get("/api/backend/operator/operators");
    expect(listRes.ok()).toBeTruthy();
    const operators = (await listRes.json()) as Array<{
      id: number;
      username: string;
      is_superuser: boolean;
      is_active: boolean;
    }>;
    const otherActiveSuperusers = operators.filter(
      (op) => op.is_superuser && op.is_active && op.id !== superuser.id,
    );
    for (const other of otherActiveSuperusers) {
      const res = await page.request.post(`/api/backend/operator/operators/${other.id}/deactivate`, {
        headers: { origin },
      });
      // 다른 superuser를 지우는 이 정리 단계 자체가 "마지막 하나"가 되기 전까지는
      // 항상 성공해야 한다(409는 이 스택에 상위 등급이 자기 자신 하나만 남았을 때만
      // 나야 정상이다).
      expect(res.status(), `cleanup deactivate of operator ${other.id}`).toBe(200);
    }

    await openOperatorsPage(page);
    const row = page.getByTestId(`operator-row-${superuser.id}`);
    await expect(row.getByTestId(`operator-row-${superuser.id}-active`)).toHaveText("활성");

    await row.getByTestId(`operator-row-${superuser.id}-deactivate`).click();

    await expect(row.getByTestId(`operator-row-${superuser.id}-action-error`)).toBeVisible();
    const message = await row.getByTestId(`operator-row-${superuser.id}-action-error`).textContent();
    expect(message).toContain("마지막");

    // 거절됐으니 여전히 활성이고, 실제로도 로그인이 계속된다 — 라벨이 아니라 효과.
    await expect(row.getByTestId(`operator-row-${superuser.id}-active`)).toHaveText("활성");
    await logout(page);
    await loginAndExpectHome(page, superuser.username);
  });
});

test.describe("일반 Operator — 403은 빈 목록이 아니다(#69)", () => {
  test("일반 Operator가 이 화면을 열면 등급이 필요하다는 취지가 보이고, 빈 목록도 깨진 화면도 아니다", async ({
    page,
  }) => {
    const ordinary = seedE2eOperator({ username: `e2e-op-mgmt-forbidden-${Date.now()}` });

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
  test("로그인하지 않은 채로 /operators를 열면 미들웨어가 렌더링 전에 /login으로 돌린다", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await page.goto("/operators");

    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByTestId("operators-heading")).toHaveCount(0);
    await expect(page.getByTestId("operators-table")).toHaveCount(0);
  });
});
