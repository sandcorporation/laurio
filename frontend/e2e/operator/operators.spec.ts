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
  test("상위 등급으로 로그인하면 Operator 목록이 아이디·등급·활성 여부와 함께 보인다", async ({
    page,
  }) => {
    const superuser = await seedE2eOperator({
      username: `e2e-op-mgmt-list-super-${Date.now()}`,
      superuser: true,
    });
    const ordinary = await seedE2eOperator({ username: `e2e-op-mgmt-list-ordinary-${Date.now()}` });

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
    const superuser = await seedE2eOperator({
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
    const superuser = await seedE2eOperator({
      username: `e2e-op-mgmt-distinct-super-${Date.now()}`,
      superuser: true,
    });
    const existing = await seedE2eOperator({ username: `e2e-op-mgmt-existing-${Date.now()}` });

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

test.describe("빈 입력 — 요청 검증 오류가 화면을 죽이지 않는다(#69)", () => {
  test("아이디·비밀번호를 비운 채 생성을 누르면 422를 받고, 화면이 죽지 않고 이유를 문자열로 보여준다", async ({
    page,
  }) => {
    // 폼에 클라이언트 검증이 없다(코드리뷰 지적) — 그래서 빈 채로 제출하면
    // 요청이 그대로 백엔드까지 가서 우리 라우터가 아니라 ninja/pydantic의
    // 요청 검증(스키마의 min_length=1)에 걸린다. 이 422의 detail은 우리
    // 라우터가 손으로 만드는 문자열(약한 비밀번호·중복 아이디 케이스)이
        // 아니라 오류 객체의 **배열**이다 — 그걸 문자열로 가정하고 그대로
    // `{error}`로 렌더하면 React가 "Objects are not valid as a React
    // child"로 화면 전체를 죽인다. operator/lib/operators/actions.ts의
    // normalizeDetail이 그 배열을 사람이 읽을 문자열로 좁혀야 이 테스트가
    // 통과한다.
    const superuser = await seedE2eOperator({
      username: `e2e-op-mgmt-emptyfields-super-${Date.now()}`,
      superuser: true,
    });

    await loginAndExpectHome(page, superuser.username);
    await openOperatorsPage(page);

    const responsePromise = page.waitForResponse(
      (res) => res.url().includes("/api/backend/operator/operators") && res.request().method() === "POST",
    );
    await page.getByTestId("create-operator-submit").click();
    const response = await responsePromise;

    // 정말로 ninja/pydantic의 요청 검증 422를 받았다는 것부터 확인한다 —
    // 우리 라우터가 만드는 422(약한 비밀번호)와는 다른 경로다.
    expect(response.status()).toBe(422);

    // 화면이 죽지 않았다 — 헤딩·표가 여전히 있고, 에러가 읽을 수 있는
    // 문자열로 보인다. "[object Object]"는 detail을 문자열로 좁히지 못했을
    // 때 나는 대표적인 증상이다.
    await expect(page.getByTestId("operators-heading")).toBeVisible();
    await expect(page.getByTestId("create-operator-error")).toBeVisible();
    const message = await page.getByTestId("create-operator-error").textContent();
    expect(message).toBeTruthy();
    expect(message).not.toContain("[object Object]");
    expect(message).not.toContain("undefined");

    // 화면이 여전히 반응한다 — 죽은 화면이라면 표도 이미 사라졌을 것이다.
    await expect(page.getByTestId("operators-table")).toBeVisible();
  });
});

test.describe("비활성화 — 효과로 증명한다(#69)", () => {
  test("Operator를 비활성화하면 그 계정으로 더 이상 로그인되지 않는다", async ({ page }) => {
    const superuser = await seedE2eOperator({
      username: `e2e-op-mgmt-deactivate-super-${Date.now()}`,
      superuser: true,
    });
    const target = await seedE2eOperator({ username: `e2e-op-mgmt-deactivate-target-${Date.now()}` });

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
    const superuser = await seedE2eOperator({
      username: `e2e-op-mgmt-reactivate-super-${Date.now()}`,
      superuser: true,
    });
    const target = await seedE2eOperator({ username: `e2e-op-mgmt-reactivate-target-${Date.now()}` });

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
    const superuser = await seedE2eOperator({
      username: `e2e-op-mgmt-last-super-${Date.now()}`,
      superuser: true,
    });

    await loginAndExpectHome(page, superuser.username);

    // 실제로 "이 스택의 마지막 활성 superuser" 상태를 만들려면 이 테스트가
    // 만들지 않은 다른 활성 superuser를 전부 비활성화해야 한다 — 그런데 그
    // 계정 중에는 개발자가 자기 `laurio-dev` 스택에 `create_operator
    // --superuser`로 만든 본인 계정도 포함될 수 있다. 실제로 그 사고가 났다
    // (코드리뷰 지적): 이 스위트를 개발자 스택에 대고 한 번 돌리면 본인
    // 계정이 영구히 잠기고, 되살리려면 이미 잠긴 그 계정의 superuser 권한이
    // 필요해 관리 명령으로 컨테이너에 들어가는 것 말고는 방법이 없어진다 —
    // ADR-0019가 남긴 바로 그 상황이고 #69는 그걸 끝내려는 화면이다. 그래서
    // 이 테스트는 이 스택에 남아 있는 다른 계정을 절대 건드리지 않는다.
    //
    // 대신 백엔드의 409(code: last_superuser) 판정 자체는
    // backend/tests/test_operator_management.py::
    // test_the_last_superuser_cannot_deactivate_themselves가 이미 HTTP로
    // 검증하고 있다 — 여기서 다시 증명할 대상이 아니다. 이 화면이 증명해야
    // 하는 것은 "그 응답을 받으면 이유를 그대로 보여주는가"라는 순수 프론트
    // 렌더링 문제이므로, 그 응답 하나만 좁게 모킹한다(home.spec.ts의 "조회
    // 실패" 테스트와 같은 원칙 — 실제 보안 판정이 아닌 순수 렌더링 상태는
    // 모킹으로 결정적으로 재현한다).
    await page.route(`**/api/backend/operator/operators/${superuser.id}/deactivate`, (route) =>
      route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({
          detail:
            "마지막 상위 등급 Operator는 비활성화할 수 없습니다 — 아무도 Operator를 만들 수 없는 상태가 됩니다.",
          code: "last_superuser",
        }),
      }),
    );

    await openOperatorsPage(page);
    const row = page.getByTestId(`operator-row-${superuser.id}`);
    await expect(row.getByTestId(`operator-row-${superuser.id}-active`)).toHaveText("활성");

    await row.getByTestId(`operator-row-${superuser.id}-deactivate`).click();

    await expect(row.getByTestId(`operator-row-${superuser.id}-action-error`)).toBeVisible();
    const message = await row.getByTestId(`operator-row-${superuser.id}-action-error`).textContent();
    expect(message).toContain("마지막");

    // 거절됐으니(모킹된 응답이지만) 화면은 여전히 활성으로 그린다 — 라벨이
    // 아니라 relay 자체를 증명한다. 실제 로그인 가능 여부는 이 계정이 실제로
    // 비활성화되지 않았으므로 별도로 재확인할 필요가 없다(애초에 이 계정에
    // 대해 실제 deactivate 호출을 보낸 적이 없다).
    await expect(row.getByTestId(`operator-row-${superuser.id}-active`)).toHaveText("활성");
  });
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

test.describe("홈에서 실제로 눌러 들어가는 경로(#69)", () => {
  // 코드리뷰 지적 — 이 화면으로 가는 링크가 앱 어디에도 없어서 URL을 직접
  // 쳐야만 들어갈 수 있었다. e2e가 전부 page.goto("/operators")였던 탓에
  // 그 사실이 가려져 있었다 — 그래서 여기서는 반드시 클릭으로 도달한다.
  test("상위 등급 홈에 계정 관리로 가는 링크가 있고, 클릭하면 /operators로 이동한다", async ({
    page,
  }) => {
    const superuser = await seedE2eOperator({
      username: `e2e-op-mgmt-navlink-super-${Date.now()}`,
      superuser: true,
    });

    await loginAndExpectHome(page, superuser.username);
    await page.getByTestId("operators-nav-link").click();

    await expect(page).toHaveURL(/\/operators$/);
    await expect(page.getByTestId("operators-heading")).toBeVisible();
  });

  test("일반 등급 홈에는 계정 관리 링크가 없다", async ({ page }) => {
    const ordinary = await seedE2eOperator({ username: `e2e-op-mgmt-navlink-ordinary-${Date.now()}` });

    await loginAndExpectHome(page, ordinary.username);

    await expect(page.getByTestId("operators-nav-link")).toHaveCount(0);
  });
});
