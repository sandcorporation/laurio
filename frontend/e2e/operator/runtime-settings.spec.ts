import { expect, test } from "@playwright/test";

import { E2E_OPERATOR_PASSWORD, seedE2eOperator } from "../lib/seed-operator";
import { establishOperatorSession } from "../lib/session";

// 운영자 앱 — 운영 설정(#922, ADR-0075). 공모전 AI 키·모델 값을 화면에서 넣고 바꾼다.
//
// 운영 설정은 플랫폼 전체의 값이라 `@exclusive`(일꾼 하나 패스)로 돈다. 각 시험은 바꾼 값을 끝에
// 지워 다음 시험이 env 출처에서 시작하게 한다. 연결 시험은 e2e 스택의 흉내 어댑터(LLM_ADAPTER_MODE
// =fake)가 받는다 — `sk-` 로 시작하는 20자 이상이면 통과, 아니면 거절. 키는 가짜 문자열이다.

const FAKE_KEY = "sk-e2e-fake-key-000000000000e2ek";
const ROW = "runtime-setting-OPEN_AI_API_KEY";
const MODEL_ROW = "runtime-setting-LLM_OPENAI_MODEL";

test.describe("운영 설정(#922)", () => {
  test("@exclusive 상위 등급이 키를 넣으면 끝 4자리만 보이고, 새로고침 뒤에도 남고, 지우면 env 로 돌아간다", async ({
    page,
  }) => {
    const su = await seedE2eOperator({ username: `e2e-op-settings-su-${Date.now()}`, superuser: true });
    await establishOperatorSession(page, su.username, E2E_OPERATOR_PASSWORD, "/settings");
    await expect(page.getByTestId(ROW)).toBeVisible();

    const input = page.getByTestId(`${ROW}-input`);
    await expect(input).toHaveAttribute("type", "password");
    await expect(input).toHaveValue("");

    await input.fill(FAKE_KEY);
    await page.getByTestId(`${ROW}-probe`).click();
    await expect(page.getByTestId(`${ROW}-probe-result`)).toHaveText("연결됨");

    await page.getByTestId(`${ROW}-save`).click();
    await expect(page.getByTestId(`${ROW}-value`)).toHaveText("설정됨 · ••••e2ek");
    await expect(page.getByTestId(`${ROW}-source`)).toHaveText("DB");
    await expect(page.getByTestId(`${ROW}-input`)).toHaveValue("");

    await page.reload();
    await expect(page.getByTestId(`${ROW}-value`)).toHaveText("설정됨 · ••••e2ek");
    await expect(page.getByTestId("runtime-settings-history")).toContainText("— → ••••e2ek");
    await expect(page.locator("body")).not.toContainText(FAKE_KEY);

    // 비운 채 저장 — 그대로다.
    await page.getByTestId(`${ROW}-save`).click();
    await expect(page.getByTestId(`${ROW}-source`)).toHaveText("DB");

    await page.getByTestId(`${ROW}-clear`).click();
    await expect(page.getByTestId(`${ROW}-source`)).not.toHaveText("DB");
    await page.reload();
    await expect(page.getByTestId(`${ROW}-source`)).not.toHaveText("DB");
    await expect(page.getByTestId(`${ROW}-clear`)).toHaveCount(0);
  });

  test("@exclusive 일반 등급은 값·출처·이력만 보고 입력·버튼이 없다", async ({ page }) => {
    const ordinary = await seedE2eOperator({ username: `e2e-op-settings-plain-${Date.now()}` });
    await establishOperatorSession(page, ordinary.username, E2E_OPERATOR_PASSWORD, "/settings");
    await expect(page.getByTestId(`${MODEL_ROW}-source`)).toBeVisible();
    await expect(page.getByTestId("runtime-settings-read-only")).toBeVisible();
    await expect(page.getByTestId(`${MODEL_ROW}-input`)).toHaveCount(0);
    await expect(page.getByTestId(`${ROW}-probe`)).toHaveCount(0);
  });
});
