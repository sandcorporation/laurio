import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { E2E_OPERATOR_PASSWORD, seedE2eOperator } from "../lib/seed-operator";
import { establishOperatorSession } from "../lib/session";

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
  await establishOperatorSession(page, username, password);
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
});

test.describe("일반 등급 — 편집 없음, 그리고 그것이 빈 화면이 아니다(#77)", () => {
  test("@exclusive 일반 등급에게는 편집 폼이 없고, 대신 등급이 필요하다는 안내가 명시적으로 보인다", async ({
    page,
  }) => {
    const ordinary = await seedE2eOperator({ username: `e2e-op-policy-forbidden-${Date.now()}` });

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
});

test.describe("세션 만료 — 스피너에 갇히지 않는다(#77, #69의 함정)", () => {
});
