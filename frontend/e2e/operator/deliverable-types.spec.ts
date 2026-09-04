import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { E2E_OPERATOR_PASSWORD, seedE2eOperator } from "../lib/seed-operator";

// 운영자 앱 — 산출물 종류(DeliverableType) 관리 화면(#80, ADR-0023).
//
// `DeliverableType`의 docstring이 "admin에서 조정한다"고 주장하던 시절은 이제
// 없다 — 이 화면과 그 뒤의 운영자 API(#80)가 유일한 조정 경로다. 최소 제안
// 상금은 "상금미달" 배지 판정에 그대로 쓰이므로 정책 화면(#77)과 같은 등급
// 규율(조회는 일반 등급도, 편집은 상위 등급만)과 오류 처리 관용구를 따른다.

function backendApiPort(): string {
  return process.env.LAURIO_API_PORT ?? "58000";
}

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

async function publicDeliverableTypeIds(page: Page): Promise<number[]> {
  const res = await page.request.get(
    `http://127.0.0.1:${backendApiPort()}/api/contests/deliverable-types`,
  );
  expect(res.ok()).toBe(true);
  const body = (await res.json()) as { id: number }[];
  return body.map((row) => row.id);
}

test.describe("조회 — 일반 등급도 활성·비활성 전부를 본다(#80)", () => {
  test("상위 등급이 홈에서 눌러 들어가면 목록과 이력, 생성 폼이 보인다", async ({ page }) => {
    const superuser = await seedE2eOperator({
      username: `e2e-op-dtype-view-super-${Date.now()}`,
      superuser: true,
    });

    await loginAndExpectHome(page, superuser.username);
    await page.getByTestId("deliverable-types-nav-link").click();

    await expect(page).toHaveURL(/\/deliverable-types$/);
    await expect(page.getByTestId("deliverable-types-heading")).toBeVisible();
    await expect(page.getByTestId("deliverable-types-table")).toBeVisible();
    await expect(page.getByTestId("create-deliverable-type-form")).toBeVisible();
  });
});

test.describe("일반 등급 — 편집 없음, 빈 화면이 아니다(#80)", () => {
  test("일반 등급은 목록을 보되 편집 컨트롤이 없고 명시적 안내가 보인다", async ({ page }) => {
    const ordinary = await seedE2eOperator({ username: `e2e-op-dtype-forbidden-${Date.now()}` });

    await loginAndExpectHome(page, ordinary.username);
    await page.getByTestId("deliverable-types-nav-link").click();

    await expect(page.getByTestId("deliverable-types-table")).toBeVisible();
    await expect(page.getByTestId("create-deliverable-type-form")).toHaveCount(0);
    await expect(page.getByTestId("deliverable-types-edit-forbidden")).toBeVisible();
    await expect(page.getByTestId("deliverable-types-edit-forbidden")).toContainText("상위 등급");
  });
});

test.describe("생성 — 상위 등급, 즉시 공개 선택지에 나타난다(#80)", () => {
  test("새 종류를 만들면 목록·공개 선택지 양쪽에 즉시 나타난다", async ({ page }) => {
    const superuser = await seedE2eOperator({
      username: `e2e-op-dtype-create-${Date.now()}`,
      superuser: true,
    });
    const typeName = `e2e 생성 종류 ${Date.now()}`;

    await loginAndExpectHome(page, superuser.username);
    await page.getByTestId("deliverable-types-nav-link").click();

    await page.getByTestId("create-deliverable-type-name").fill(typeName);
    await page.getByTestId("create-deliverable-type-minimum-prize").fill("350000");
    await page.getByTestId("create-deliverable-type-reason").fill("e2e 생성 사유");
    await page.getByTestId("create-deliverable-type-submit").click();

    await expect(page.getByTestId("create-deliverable-type-error")).toHaveCount(0);

    const row = page.locator('tr[data-testid^="deliverable-type-row-"]', { hasText: typeName });
    await expect(row).toBeVisible();

    // 공개 선택지(Contest 개최 화면이 읽는 것과 같은 엔드포인트)에도 즉시
    // 나타난다 — 캐시된 목록이 아니라 매 요청마다 다시 조회하기 때문이다.
    const nameCell = row.locator('[data-testid$="-name"]');
    await expect(nameCell).toHaveText(typeName);
  });

  test("이유 없이 생성하려 하면 거부되고 그 이유가 화면에 보인다", async ({ page }) => {
    const superuser = await seedE2eOperator({
      username: `e2e-op-dtype-create-noreason-${Date.now()}`,
      superuser: true,
    });

    await loginAndExpectHome(page, superuser.username);
    await page.getByTestId("deliverable-types-nav-link").click();

    await page.getByTestId("create-deliverable-type-name").fill(`이유없음-${Date.now()}`);
    await page.getByTestId("create-deliverable-type-minimum-prize").fill("100000");
    await page.getByTestId("create-deliverable-type-submit").click();

    await expect(page.getByTestId("create-deliverable-type-error")).toBeVisible();
    await expect(page.getByTestId("create-deliverable-type-error")).toContainText("이유");
  });

  test("최소 제안 상금 칸을 비운 채 생성하면 0원 종류가 조용히 만들어지지 않는다(코드리뷰 지적)", async ({
    page,
  }) => {
    // `Number("")`는 NaN이 아니라 0이다 — 최소 제안 상금을 비운 채 생성하면
    // 0원짜리 종류가 조용히 만들어질 뻔했다. 이름은 unique이고 되살리는
    // 경로가 없어(#80은 비활성화만 만든다) 그 이름이 영구히 묶인다.
    const superuser = await seedE2eOperator({
      username: `e2e-op-dtype-create-emptyprize-${Date.now()}`,
      superuser: true,
    });
    const typeName = `이유있음-빈상금-${Date.now()}`;

    await loginAndExpectHome(page, superuser.username);
    await page.getByTestId("deliverable-types-nav-link").click();

    await page.getByTestId("create-deliverable-type-name").fill(typeName);
    // 최소 제안 상금 칸은 비워 둔다.
    await page.getByTestId("create-deliverable-type-reason").fill("빈 상금 시도");

    const responsePromise = page.waitForResponse(
      (res) => res.url().includes("/api/backend/operator/deliverable-types") && res.request().method() === "POST",
    );
    await page.getByTestId("create-deliverable-type-submit").click();
    const response = await responsePromise;

    // 200/201이 아니어야 한다 — 성공했다면 0원짜리 종류가 조용히 생겼다는
    // 뜻이다.
    expect(response.ok()).toBe(false);
    await expect(page.getByTestId("create-deliverable-type-error")).toBeVisible();

    const row = page.locator('tr[data-testid^="deliverable-type-row-"]', { hasText: typeName });
    await expect(row).toHaveCount(0);
  });
});

test.describe("수정 — 최소 제안 상금, 이유가 함께 남는다(#80)", () => {
  test("상위 등급이 최소 제안 상금을 바꾸면 표와 이력이 새 값을 보여준다", async ({ page }) => {
    const superuser = await seedE2eOperator({
      username: `e2e-op-dtype-update-${Date.now()}`,
      superuser: true,
    });
    const typeName = `e2e 수정 대상 ${Date.now()}`;
    const reason = `e2e 수정 사유 ${Date.now()}`;

    await loginAndExpectHome(page, superuser.username);
    await page.getByTestId("deliverable-types-nav-link").click();

    await page.getByTestId("create-deliverable-type-name").fill(typeName);
    await page.getByTestId("create-deliverable-type-minimum-prize").fill("400000");
    await page.getByTestId("create-deliverable-type-reason").fill("초기 생성");
    await page.getByTestId("create-deliverable-type-submit").click();

    const row = page.locator('tr[data-testid^="deliverable-type-row-"]', { hasText: typeName });
    await expect(row).toBeVisible();
    const rowTestId = await row.getAttribute("data-testid");
    if (!rowTestId) throw new Error("행의 data-testid를 찾지 못했다");

    await page.getByTestId(`${rowTestId}-edit-button`).click();
    await page.getByTestId(`${rowTestId}-edit-minimum-prize`).fill("650000");
    await page.getByTestId(`${rowTestId}-edit-reason`).fill(reason);
    await page.getByTestId(`${rowTestId}-edit-save`).click();

    await expect(page.getByTestId(`${rowTestId}-minimum-prize`)).toHaveText("650000");

    const historyTable = page.getByTestId("deliverable-type-history-table");
    await expect(historyTable).toBeVisible();
    await expect(historyTable).toContainText(reason);
  });

  test("최소 제안 상금 칸을 비운 채 수정하면 조용히 0원이 되지 않는다(코드리뷰 지적)", async ({
    page,
  }) => {
    // `Number("")`는 NaN이 아니라 0이다 — 비운 채 저장하면 그 종류의
    // "상금미달" 배지 판정이 사실상 꺼질 뻔했다.
    const superuser = await seedE2eOperator({
      username: `e2e-op-dtype-update-emptyprize-${Date.now()}`,
      superuser: true,
    });
    const typeName = `e2e 빈상금수정 대상 ${Date.now()}`;

    await loginAndExpectHome(page, superuser.username);
    await page.getByTestId("deliverable-types-nav-link").click();

    await page.getByTestId("create-deliverable-type-name").fill(typeName);
    await page.getByTestId("create-deliverable-type-minimum-prize").fill("450000");
    await page.getByTestId("create-deliverable-type-reason").fill("초기 생성");
    await page.getByTestId("create-deliverable-type-submit").click();

    const row = page.locator('tr[data-testid^="deliverable-type-row-"]', { hasText: typeName });
    await expect(row).toBeVisible();
    const rowTestId = await row.getAttribute("data-testid");
    if (!rowTestId) throw new Error("행의 data-testid를 찾지 못했다");

    await page.getByTestId(`${rowTestId}-edit-button`).click();
    await page.getByTestId(`${rowTestId}-edit-minimum-prize`).fill("");
    await page.getByTestId(`${rowTestId}-edit-reason`).fill("빈 상금 수정 시도");

    const responsePromise = page.waitForResponse(
      (res) => /\/api\/backend\/operator\/deliverable-types\/\d+$/.test(res.url()) && res.request().method() === "POST",
    );
    await page.getByTestId(`${rowTestId}-edit-save`).click();
    const response = await responsePromise;

    expect(response.ok()).toBe(false);

    // 실패한 시도는 여전히 편집 모드에 머문다(입력칸이 비어 있는 그대로) —
    // 그 셀 자체는 지금 <input>이라 텍스트로 읽을 수 없다. 서버에 실제로
    // 반영되지 않았는지는 새로고침해 view 모드로 돌아온 값으로 확인한다 —
    // 클라이언트의 낙관이 아니라 서버 상태를 직접 증명한다.
    await page.reload();
    const reloadedRow = page.locator('tr[data-testid^="deliverable-type-row-"]', {
      hasText: typeName,
    });
    await expect(reloadedRow.getByTestId(`${rowTestId}-minimum-prize`)).toHaveText("450000");
  });
});

test.describe("비활성화 — 지우지 않는다, 공개 선택지에서만 빠진다(#80)", () => {
  test("비활성화하면 활성 여부가 바뀌고 공개 목록에서 사라지지만 행 자체는 남는다", async ({
    page,
  }) => {
    const superuser = await seedE2eOperator({
      username: `e2e-op-dtype-deactivate-${Date.now()}`,
      superuser: true,
    });
    const typeName = `e2e 비활성화 대상 ${Date.now()}`;

    await loginAndExpectHome(page, superuser.username);
    await page.getByTestId("deliverable-types-nav-link").click();

    await page.getByTestId("create-deliverable-type-name").fill(typeName);
    await page.getByTestId("create-deliverable-type-minimum-prize").fill("200000");
    await page.getByTestId("create-deliverable-type-reason").fill("초기 생성");
    await page.getByTestId("create-deliverable-type-submit").click();

    const row = page.locator('tr[data-testid^="deliverable-type-row-"]', { hasText: typeName });
    await expect(row).toBeVisible();
    const rowTestId = await row.getAttribute("data-testid");
    if (!rowTestId) throw new Error("행의 data-testid를 찾지 못했다");
    const typeId = Number(rowTestId.replace("deliverable-type-row-", ""));

    const beforeIds = await publicDeliverableTypeIds(page);
    expect(beforeIds).toContain(typeId);

    await page.getByTestId(`${rowTestId}-deactivate-button`).click();
    await page.getByTestId(`${rowTestId}-deactivate-reason`).fill("더 이상 제공하지 않음");
    await page.getByTestId(`${rowTestId}-deactivate-confirm`).click();

    await expect(page.getByTestId(`${rowTestId}-active`)).toHaveText("비활성");
    // 지워지지 않았다 — 행은 여전히 화면에 있다(활성 여부만 바뀌었다).
    await expect(row).toBeVisible();

    const afterIds = await publicDeliverableTypeIds(page);
    expect(afterIds).not.toContain(typeId);
  });
});

test.describe("세션 만료 — 스피너에 갇히지 않는다(#80, #69의 함정)", () => {
  test("세션이 아예 없으면 렌더링 전에 로그인으로 돌아간다", async ({ page, context }) => {
    await context.clearCookies();
    await page.goto("/deliverable-types");

    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByTestId("deliverable-types-heading")).toHaveCount(0);
  });

  test("생성 중 세션이 만료되면 로그인으로 돌아간다", async ({ page }) => {
    const superuser = await seedE2eOperator({
      username: `e2e-op-dtype-expire-${Date.now()}`,
      superuser: true,
    });

    await loginAndExpectHome(page, superuser.username);
    await page.getByTestId("deliverable-types-nav-link").click();

    await page.route("**/api/backend/operator/deliverable-types", (route) => {
      if (route.request().method() === "POST") {
        return route.fulfill({ status: 401, body: JSON.stringify({ detail: "세션이 만료되었습니다." }) });
      }
      return route.continue();
    });

    await page.getByTestId("create-deliverable-type-name").fill(`만료시나리오-${Date.now()}`);
    await page.getByTestId("create-deliverable-type-minimum-prize").fill("100000");
    await page.getByTestId("create-deliverable-type-reason").fill("세션 만료 시나리오");
    await page.getByTestId("create-deliverable-type-submit").click();

    await expect(page).toHaveURL(/\/login/);
  });
});
