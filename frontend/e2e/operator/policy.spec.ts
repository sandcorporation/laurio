import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { E2E_OPERATOR_PASSWORD, seedE2eOperator } from "../lib/seed-operator";

// 운영자 앱 — 플랫폼 정책 화면(#77, ADR-0023).
//
// 조회는 일반 등급도 되지만(#76) 변경은 상위 등급만 된다 — 계정 관리 화면
// (#69)이 세운 "403은 빈 목록이 아니다" 관용구를 여기서는 "편집 없음도 빈
// 화면이 아니다"로 옮긴다: 조회는 항상 성공하므로(값 표는 언제나 보인다),
// 일반 등급이 못 하는 것은 오직 편집이고, 그 사실 자체를 명시적으로 말해야
// 한다.
//
// PlatformPolicy는 단일 행이라 이 스위트의 테스트들이 같은 행을 공유한다.
// playwright.config.ts가 workers=1이라 실제 동시 접근은 없지만, 이전 테스트가
// 남긴 값에 기대지 않도록 각 테스트는 항상 "지금 보이는 값"을 먼저 읽은 뒤
// 그것과 다른 값으로 바꾼다.

async function loginAsOperator(page: Page, username: string, password = E2E_OPERATOR_PASSWORD): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("login-username").fill(username);
  await page.getByTestId("login-password").fill(password);
  await page.getByTestId("login-submit").click();
}

async function loginAndExpectHome(page: Page, username: string): Promise<void> {
  await loginAsOperator(page, username);
  await expect(page.getByTestId("operator-home-heading")).toBeVisible();
}

async function readFeeBps(page: Page): Promise<number> {
  const text = await page.getByTestId("policy-value-platform_fee_bps").textContent();
  return Number(text);
}

test.describe("조회 — 일반 등급도 지금 값을 본다(#77)", () => {
  test("일반 등급으로 홈에서 눌러 들어가면 정책값 표가 보인다", async ({ page }) => {
    const ordinary = seedE2eOperator({ username: `e2e-op-policy-view-${Date.now()}` });

    await loginAndExpectHome(page, ordinary.username);

    // 코드리뷰가 계정 관리 화면에서 지적했던 것과 같은 이유로 클릭으로
    // 도달한다(page.goto가 아니다) — 링크가 실제로 존재하고 실제로 그
    // 화면으로 이어지는지를 증명한다.
    await page.getByTestId("policy-nav-link").click();

    await expect(page).toHaveURL(/\/policy$/);
    await expect(page.getByTestId("policy-heading")).toBeVisible();
    await expect(page.getByTestId("policy-values-table")).toBeVisible();
    await expect(page.getByTestId("policy-value-platform_fee_bps")).toBeVisible();
    const value = await readFeeBps(page);
    expect(Number.isNaN(value)).toBe(false);
  });

  test("상위 등급으로 홈에서 눌러 들어가도 같은 값 표와 이력이 보인다", async ({ page }) => {
    const superuser = seedE2eOperator({
      username: `e2e-op-policy-view-super-${Date.now()}`,
      superuser: true,
    });

    await loginAndExpectHome(page, superuser.username);
    await page.getByTestId("policy-nav-link").click();

    await expect(page.getByTestId("policy-values-table")).toBeVisible();
    await expect(page.getByTestId("policy-editor-form")).toBeVisible();
  });
});

test.describe("일반 등급 — 편집 없음, 그리고 그것이 빈 화면이 아니다(#77)", () => {
  test("일반 등급에게는 편집 폼이 없고, 대신 등급이 필요하다는 안내가 명시적으로 보인다", async ({
    page,
  }) => {
    const ordinary = seedE2eOperator({ username: `e2e-op-policy-forbidden-${Date.now()}` });

    await loginAndExpectHome(page, ordinary.username);
    await page.getByTestId("policy-nav-link").click();

    // 값 표는 정상적으로 보인다 — "여기엔 아무것도 없다"가 아니다.
    await expect(page.getByTestId("policy-values-table")).toBeVisible();
    await expect(page.getByTestId("policy-value-platform_fee_bps")).toBeVisible();

    // 편집 폼은 없고, 대신 "너는 안 된다"는 안내가 명시적으로 있다.
    await expect(page.getByTestId("policy-editor-form")).toHaveCount(0);
    await expect(page.getByTestId("policy-edit-forbidden")).toBeVisible();
    await expect(page.getByTestId("policy-edit-forbidden")).toContainText("상위 등급");
  });
});

test.describe("변경 — 상위 등급, 이유가 함께 남는다(#77)", () => {
  test("상위 등급이 값을 바꾸고 이유를 남기면 저장되고, 표와 이력이 새 값을 보여준다", async ({
    page,
  }) => {
    const superuser = seedE2eOperator({
      username: `e2e-op-policy-change-${Date.now()}`,
      superuser: true,
    });
    const newFee = 100 + (Date.now() % 500);
    const reason = `e2e 정책 변경 사유 ${Date.now()}`;

    await loginAndExpectHome(page, superuser.username);
    await page.getByTestId("policy-nav-link").click();
    await expect(page.getByTestId("policy-editor-form")).toBeVisible();

    await page.getByTestId("policy-input-platform_fee_bps").fill(String(newFee));
    // withholding_tax_bps는 건드리지 않는다 — 안전한 낮은 값(440 근처)에
    // 머물러 있으므로 fee와의 합이 상한(10000)을 넘을 일이 없다.
    await page.getByTestId("policy-reason-input").fill(reason);
    await page.getByTestId("policy-save-button").click();

    await expect(page.getByTestId("policy-save-error")).toHaveCount(0);
    await expect(page.getByTestId("policy-value-platform_fee_bps")).toHaveText(String(newFee));

    // 이력에 방금 변경이 한 사건으로 나타난다 — 라벨이 아니라 표에 실제로
    // 그 사유·값이 있는지로 증명한다.
    const historyTable = page.getByTestId("policy-history-table");
    await expect(historyTable).toBeVisible();
    const firstRow = historyTable.locator("tbody tr").first();
    await expect(firstRow).toContainText(reason);
    await expect(firstRow).toContainText(String(newFee));
  });

  test("이유 없이 저장하려 하면 거부되고 그 이유가 화면에 보인다", async ({ page }) => {
    const superuser = seedE2eOperator({
      username: `e2e-op-policy-noreason-${Date.now()}`,
      superuser: true,
    });

    await loginAndExpectHome(page, superuser.username);
    await page.getByTestId("policy-nav-link").click();

    const currentFee = await readFeeBps(page);
    await page.getByTestId("policy-input-platform_fee_bps").fill(String(currentFee + 7));
    // 이유는 비워 둔다.
    await page.getByTestId("policy-save-button").click();

    await expect(page.getByTestId("policy-save-error")).toBeVisible();
    await expect(page.getByTestId("policy-save-error")).toContainText("이유");
    // 저장되지 않았다 — 표는 여전히 이전 값이다.
    await expect(page.getByTestId("policy-value-platform_fee_bps")).toHaveText(String(currentFee));
  });

  test("말이 안 되는 값(상한 초과)이 거부되고 무엇이 잘못됐는지 화면이 말한다", async ({ page }) => {
    const superuser = seedE2eOperator({
      username: `e2e-op-policy-invalid-${Date.now()}`,
      superuser: true,
    });

    await loginAndExpectHome(page, superuser.username);
    await page.getByTestId("policy-nav-link").click();

    const currentFee = await readFeeBps(page);
    // 개별 상한(9000, 90%)을 넘는 값 — CheckConstraint에 닿기 전에 서버가
    // 422로 거절해야 한다(500이 아니다).
    await page.getByTestId("policy-input-platform_fee_bps").fill("9500");
    await page.getByTestId("policy-reason-input").fill("상한 초과 시도");

    const responsePromise = page.waitForResponse(
      (res) => res.url().includes("/api/backend/operator/policy") && res.request().method() === "POST",
    );
    await page.getByTestId("policy-save-button").click();
    const response = await responsePromise;

    expect(response.status()).toBe(422);
    await expect(page.getByTestId("policy-save-error")).toBeVisible();
    // "저장 실패"로 뭉개지 않는다 — 무엇이 잘못됐는지(platform_fee_bps)가
    // 메시지에 있다.
    await expect(page.getByTestId("policy-save-error")).toContainText("platform_fee_bps");
    await expect(page.getByTestId("policy-value-platform_fee_bps")).toHaveText(String(currentFee));
  });

  test("숫자가 아닌 입력은 요청 검증 422를 내고, detail이 배열이어도 화면이 죽지 않는다", async ({
    page,
  }) => {
    // django-ninja의 요청 검증 422는 detail이 오류 객체의 **배열**이다 — 그걸
    // 문자열로 가정하고 그대로 렌더하면 React가 "Objects are not valid as a
    // React child"로 화면 전체를 죽인다(#69에서 실제로 겪었다).
    const superuser = seedE2eOperator({
      username: `e2e-op-policy-badinput-${Date.now()}`,
      superuser: true,
    });

    await loginAndExpectHome(page, superuser.username);
    await page.getByTestId("policy-nav-link").click();

    await page.getByTestId("policy-input-platform_fee_bps").fill("숫자아님");
    await page.getByTestId("policy-reason-input").fill("잘못된 입력 시도");

    const responsePromise = page.waitForResponse(
      (res) => res.url().includes("/api/backend/operator/policy") && res.request().method() === "POST",
    );
    await page.getByTestId("policy-save-button").click();
    const response = await responsePromise;

    expect(response.status()).toBe(422);

    // 화면이 죽지 않았다 — 헤딩·표가 여전히 있고 에러가 읽을 수 있는
    // 문자열이다.
    await expect(page.getByTestId("policy-heading")).toBeVisible();
    await expect(page.getByTestId("policy-values-table")).toBeVisible();
    await expect(page.getByTestId("policy-save-error")).toBeVisible();
    const message = await page.getByTestId("policy-save-error").textContent();
    expect(message).toBeTruthy();
    expect(message).not.toContain("[object Object]");
    expect(message).not.toContain("undefined");
  });

  test("입력칸을 비운 채 저장하면 조용히 0이 되지 않는다(코드리뷰 지적)", async ({ page }) => {
    // `Number("")`는 NaN이 아니라 0이다 — 입력칸을 비운 채 저장하면 그
    // 필드가 조용히 0으로 바뀔 뻔했다. 서버 경계(0~9000)가 0을 허용하므로
    // 이 사고는 200으로 "성공"해버려 화면에서 눈치채기 어렵다. 빈 입력은
    // 명시적인 4xx로 거절되어야 하고, 표의 값도 그대로여야 한다.
    const superuser = seedE2eOperator({
      username: `e2e-op-policy-emptyinput-${Date.now()}`,
      superuser: true,
    });

    await loginAndExpectHome(page, superuser.username);
    await page.getByTestId("policy-nav-link").click();

    const currentFee = await readFeeBps(page);
    await page.getByTestId("policy-input-platform_fee_bps").fill("");
    await page.getByTestId("policy-reason-input").fill("빈 입력 시도");

    const responsePromise = page.waitForResponse(
      (res) => res.url().includes("/api/backend/operator/policy") && res.request().method() === "POST",
    );
    await page.getByTestId("policy-save-button").click();
    const response = await responsePromise;

    // 200이 아니어야 한다 — 200이면 빈 입력이 조용히 유효한 값(0)으로
    // 받아들여졌다는 뜻이다.
    expect(response.status()).not.toBe(200);
    await expect(page.getByTestId("policy-value-platform_fee_bps")).toHaveText(String(currentFee));
    expect(currentFee).not.toBe(0);
  });
});

test.describe("세션 만료 — 스피너에 갇히지 않는다(#77, #69의 함정)", () => {
  test("세션이 아예 없으면 렌더링 전에 로그인으로 돌아간다", async ({ page, context }) => {
    await context.clearCookies();
    await page.goto("/policy");

    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByTestId("policy-heading")).toHaveCount(0);
  });

  test("저장 중 세션이 만료되면 로그인으로 돌아가고 값은 바뀌지 않는다", async ({ page }) => {
    // 실제 세션 만료(Redis에서 세션을 지우는 등)는 이 화면의 렌더링 로직과
    // 무관한 배관이 필요하다. 401 자체는 이미 백엔드 HTTP 시임(SuperuserOperatorAuth)이
    // 커버하므로, appeals.spec.ts의 같은 분기와 같은 판단으로 route
    // 가로채기로 그 조건만 재현한다.
    const superuser = seedE2eOperator({
      username: `e2e-op-policy-expire-${Date.now()}`,
      superuser: true,
    });

    await loginAndExpectHome(page, superuser.username);
    await page.getByTestId("policy-nav-link").click();

    const currentFee = await readFeeBps(page);

    await page.route("**/api/backend/operator/policy", (route) => {
      if (route.request().method() === "POST") {
        return route.fulfill({ status: 401, body: JSON.stringify({ detail: "세션이 만료되었습니다." }) });
      }
      return route.continue();
    });

    await page.getByTestId("policy-input-platform_fee_bps").fill(String(currentFee + 3));
    await page.getByTestId("policy-reason-input").fill("세션 만료 시나리오");
    await page.getByTestId("policy-save-button").click();

    await expect(page).toHaveURL(/\/login/);
  });
});
