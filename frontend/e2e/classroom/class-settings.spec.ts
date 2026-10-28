import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 클래스 설정(시안 v2, #636): 채점 연결 상태 줄과 「바꾸기」, 기본 모델 라디오 표, 템플릿 공개,
// 그리고 클래스 상세에서 옮겨 온 보관·되돌리기·복사. 클래스 삭제는 class-deletion.spec.ts 가 걷는다.
// 서버 상태를 바꾸는 행동은 새로고침해서 서버에 남았는지까지 본다. 준비는 API 로 한다(시임 규약).

async function newClass(page: import("@playwright/test").Page, label: string) {
  await establishClassroomSession(page, `class-settings-${label}-${test.info().workerIndex}-${Date.now()}`);
  const api = classroomApi(page);
  const created = await api.post("/api/backend/classroom/classes", {
    data: { name: `설정 확인 ${label} ${Date.now()}`, instructor_display_name: "강사" },
  });
  expect(created.ok()).toBeTruthy();
  return { api, classId: (await created.json()).id as number };
}

test("채점 연결은 「연결 없음」에서 시작해 키를 저장하면 상태 줄이 연결됨이 되고, 새로고침해도 남고, 바꾸기를 눌러야 폼이 열린다", async ({
  page,
}) => {
  const { classId } = await newClass(page, "key");
  await page.goto(`/classes/${classId}/settings#scoring-key`);

  await expect(page.getByTestId("openai-key-status")).toContainText("연결 없음");
  await page.getByTestId("openai-key-input").fill("sk-e2e-test-key-7f2a");
  await page.getByTestId("openai-key-submit").click();

  await expect(page.getByTestId("openai-key-status")).toContainText("연결됨");
  await expect(page.getByTestId("openai-key-status")).toContainText("7f2a");
  await expect(page.getByTestId("scoring-connection-verified")).toHaveText(/^\d{1,2}\/\d{1,2} 확인$/);
  await expect(page.getByTestId("openai-key-input")).toHaveCount(0);

  await page.reload();
  await expect(page.getByTestId("openai-key-status")).toContainText("7f2a");
  await expect(page.getByTestId("openai-key-input")).toHaveCount(0);
  await page.getByTestId("scoring-connection-change").click();
  await expect(page.getByTestId("openai-key-input")).toBeVisible();
});

test("「Claude(Anthropic) 키」를 고르고 저장하면 상태 줄이 그 종류와 끝 네 자리로 연결됨이 되고, 새로고침해도 남는다", async ({
  page,
}) => {
  const { classId } = await newClass(page, "claude");
  await page.goto(`/classes/${classId}/settings#scoring-key`);

  await page.getByTestId("scoring-connection-kind-anthropic_key").click();
  await page.getByTestId("anthropic-key-input").fill("sk-ant-e2e-test-key-9c1d");
  await page.getByTestId("anthropic-key-submit").click();

  await expect(page.getByTestId("anthropic-key-status")).toContainText("연결됨");
  await expect(page.getByTestId("anthropic-key-status")).toContainText("Claude(Anthropic) 키");
  await expect(page.getByTestId("anthropic-key-status")).toContainText("9c1d");
  await expect(page.getByTestId("anthropic-key-input")).toHaveCount(0);
  // 새로고침 없이도 단가표에 있는 Claude 모델은 원화로 보인다(#801) — 비용은 연결이 바뀐 뒤에 다시 받는다.
  await expect(page.getByTestId("scoring-model-cost-claude-haiku-5-5")).toContainText("원");
  await expect(page.getByTestId("scoring-model-cost-claude-sonnet-5-5")).not.toContainText("비용 미확인");

  await page.reload();
  await expect(page.getByTestId("anthropic-key-status")).toContainText("9c1d");
  await expect(page.getByTestId("scoring-model-cost-claude-haiku-5-5")).toContainText("원");
});

test("기본 모델은 라디오 표에서 골라 저장하고, 새로고침해도 그 모델이 기본값이다", async ({ page }) => {
  const { api, classId } = await newClass(page, "model");
  const key = await api.put(`/api/backend/classroom/classes/${classId}/openai-key`, {
    data: { api_key: "sk-e2e-test-key" },
  });
  expect(key.ok()).toBeTruthy();

  await page.goto(`/classes/${classId}/settings#scoring-model`);
  const table = page.getByTestId("class-default-model-table");
  await expect(table).toBeVisible();
  // 고르는 것은 두 번째 줄 — 지금 기본값은 맨 위에 있다.
  const radios = table.getByRole("radio");
  const second = radios.nth(1);
  const secondModel = await second.getAttribute("value");
  expect(secondModel).toBeTruthy();
  await second.check();
  await page.getByTestId("class-default-model-submit").click();

  await expect
    .poll(async () => (await (await api.get(`/api/backend/classroom/classes/${classId}`)).json()).default_model)
    .toBe(secondModel);
  await page.reload();
  await expect(page.getByTestId(`scoring-model-option-${secondModel}`)).toBeChecked();
});

test("템플릿으로 공개하면 공유 주소가 나오고 새로고침해도 공개 상태다", async ({ page }) => {
  const { classId } = await newClass(page, "template");
  await page.goto(`/classes/${classId}/settings#class-template`);

  await page.getByTestId("publish-class-template-name-input").fill("김강사");
  await page.getByTestId("publish-class-template-submit").click();
  await expect(page.getByTestId("publish-class-template-done")).toBeVisible();
  await expect(page.getByTestId("publish-class-template-share-link")).toBeVisible();

  await page.reload();
  await expect(page.getByTestId("publish-class-template-share-link")).toBeVisible();
  await expect(page.getByTestId("publish-class-template-name-input")).toHaveCount(0);
});

test("보관하면 설정이 보관됨이 되고 새로고침해도 남는다", async ({ page }) => {
  const { classId } = await newClass(page, "archive");
  await page.goto(`/classes/${classId}/settings`);

  await expect(page.getByTestId("class-archive-status")).toHaveText("진행중");
  await page.getByTestId("classroom-archive").click();
  await expect(page.getByTestId("class-archive-status")).toHaveText("보관됨");
  await page.reload();
  await expect(page.getByTestId("class-archive-status")).toHaveText("보관됨");
});

test("보관을 되돌리면 진행중으로 돌아오고 새로고침해도 남는다", async ({ page }) => {
  const { api, classId } = await newClass(page, "unarchive");
  expect((await api.post(`/api/backend/classroom/classes/${classId}/archive`)).ok()).toBeTruthy();
  await page.goto(`/classes/${classId}/settings`);

  await page.getByTestId("classroom-unarchive").click();
  await expect(page.getByTestId("class-archive-status")).toHaveText("진행중");
  await page.reload();
  await expect(page.getByTestId("class-archive-status")).toHaveText("진행중");
});

test("보관된 클래스 상세에서 설정 링크 한 번이면 복사에 닿고, 복사하면 새 클래스의 상세로 간다", async ({ page }) => {
  const { api, classId } = await newClass(page, "copy");
  expect((await api.post(`/api/backend/classroom/classes/${classId}/archive`)).ok()).toBeTruthy();

  await page.goto(`/classes/${classId}`);
  await expect(page.getByTestId("classroom-archived-banner")).toBeVisible();
  await page.getByTestId("class-settings-link").click();
  await expect(page).toHaveURL(new RegExp(`/classes/${classId}/settings#class-archive$`));
  // 구획은 클래스를 읽은 뒤 그려진다 — 그래도 도착하면 「보관과 삭제」가 화면 안이다(#658).
  await expect(page.getByTestId("copy-class-button")).toBeInViewport();
  // 맨 아래 짧은 구획이라도 도착한 구획이 목차의 지금 위치다(#664).
  await expect(page.getByTestId("settings-toc-class-archive")).toHaveAttribute("aria-current", "true");

  await page.getByTestId("copy-class-button").click();
  await expect(page).toHaveURL(/\/classes\/\d+$/);
  expect(page.url()).not.toContain(`/classes/${classId}`);
});
