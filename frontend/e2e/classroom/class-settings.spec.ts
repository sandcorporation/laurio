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

test("채점 연결은 「연결 없음」에서 시작해 OpenAI 키를 넣으면 상태 줄이 연결됨이 되고, 새로고침해도 남는다", async ({
  page,
}) => {
  const { classId } = await newClass(page, "key");
  await page.goto(`/classes/${classId}/settings#scoring-key`);

  await expect(page.getByTestId("openai-key-status")).toContainText("연결 없음");
  await expect(page.getByTestId("scoring-connection-kind-openai_key")).toBeDisabled();
  await page.getByTestId("vendor-key-openai-change").click();
  await page.getByTestId("openai-key-input").fill("sk-e2e-test-key-7f2a");
  await page.getByTestId("openai-key-submit").click();

  await expect(page.getByTestId("openai-key-status")).toContainText("연결됨");
  await expect(page.getByTestId("openai-key-status")).toContainText("7f2a");
  await expect(page.getByTestId("scoring-connection-verified")).toHaveText(/^\d{1,2}\/\d{1,2} 확인$/);
  await expect(page.getByTestId("openai-key-input")).toHaveCount(0);
  await expect(page.getByTestId("vendor-key-openai-masked")).toContainText("7f2a");
  await expect(page.getByTestId("scoring-connection-kind-openai_key")).toHaveAttribute("aria-checked", "true");

  await page.reload();
  await expect(page.getByTestId("openai-key-status")).toContainText("7f2a");
  await expect(page.getByTestId("openai-key-input")).toHaveCount(0);
  await page.getByTestId("vendor-key-openai-change").click();
  await expect(page.getByTestId("openai-key-input")).toBeVisible();
});

test("OpenAI·Claude 키를 둘 다 넣어 두고 스위치로 채점 벤더를 바꾸면 상태 줄과 모델 표가 따라가고, 새로고침해도 남는다", async ({
  page,
}) => {
  const { api, classId } = await newClass(page, "claude");
  const key = await api.put(`/api/backend/classroom/classes/${classId}/openai-key`, {
    data: { api_key: "sk-e2e-test-key-7f2a" },
  });
  expect(key.ok()).toBeTruthy();
  await page.goto(`/classes/${classId}/settings#scoring-key`);

  // 방침 개정 시행일(#803) 전에는 Claude 키 줄과 선택지가 없고, 지나면 저절로 열린다 — 어느 쪽이든 이 시험이 맞아야 한다.
  await expect(page.getByTestId("vendor-key-openai")).toBeVisible();
  if ((await page.getByTestId("vendor-key-anthropic").count()) === 0) {
    await expect(page.getByTestId("scoring-connection-kind-anthropic_key")).toHaveCount(0);
    return;
  }
  await expect(page.getByTestId("scoring-connection-kind-anthropic_key")).toBeDisabled();
  await page.getByTestId("vendor-key-anthropic-change").click();
  await page.getByTestId("anthropic-key-input").fill("sk-ant-e2e-test-key-9c1d");
  await page.getByTestId("anthropic-key-submit").click();

  // 쉬는 쪽 키를 넣어도 채점은 OpenAI 그대로다.
  await expect(page.getByTestId("vendor-key-anthropic-masked")).toContainText("9c1d");
  await expect(page.getByTestId("openai-key-status")).toContainText("7f2a");

  await page.getByTestId("scoring-connection-kind-anthropic_key").click();
  await expect(page.getByTestId("anthropic-key-status")).toContainText("Claude(Anthropic) 키");
  await expect(page.getByTestId("anthropic-key-status")).toContainText("9c1d");
  await expect(page.getByTestId("vendor-key-openai-masked")).toContainText("7f2a");
  // 새로고침 없이도 단가표에 있는 Claude 모델은 원화로 보인다(#801) — 비용은 연결이 바뀐 뒤에 다시 받는다.
  await expect(page.getByTestId("scoring-model-cost-claude-haiku-5-5")).toContainText("원");
  await expect(page.getByTestId("scoring-model-cost-claude-sonnet-5-5")).not.toContainText("단가 모름");

  await page.reload();
  await expect(page.getByTestId("anthropic-key-status")).toContainText("9c1d");
  await expect(page.getByTestId("scoring-model-cost-claude-haiku-5-5")).toContainText("원");

  await page.getByTestId("scoring-connection-kind-openai_key").click();
  await expect(page.getByTestId("openai-key-status")).toContainText("7f2a");
  await page.reload();
  await expect(page.getByTestId("openai-key-status")).toContainText("7f2a");
  await expect(page.getByTestId("scoring-connection-kind-openai_key")).toHaveAttribute("aria-checked", "true");
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

test("채점·완성도 검사 방식 — OpenAI 키 클래스는 「한 번 호출」이 켜져 있고 「에이전트」는 꺼진 채 까닭이 툴팁이다", async ({
  page,
}) => {
  const { classId } = await newClass(page, "method");
  await page.goto(`/classes/${classId}/settings#scoring-key`);
  await page.getByTestId("vendor-key-openai-change").click();
  await page.getByTestId("openai-key-input").fill("sk-e2e-test-key-7f2a");
  await page.getByTestId("openai-key-submit").click();
  await expect(page.getByTestId("openai-key-status")).toContainText("연결됨");

  for (const id of ["scoring-method", "quality-method"]) {
    await expect(page.getByTestId(`${id}-single`)).toHaveAttribute("aria-checked", "true");
    await expect(page.getByTestId(`${id}-agent`)).toBeDisabled();
    await expect(page.getByTestId(`${id}-agent`)).toHaveAttribute("title", "OpenAI 키는 확인 전");
    await expect(page.getByTestId(`${id}-vendor`)).toHaveText("OpenAI");
  }

  await page.reload();
  await expect(page.getByTestId("scoring-method-single")).toHaveAttribute("aria-checked", "true");
});

test("채점 비용 계산기 — 프로바이더·방식·모델·체크리스트·소스 크기를 바꾸면 제출 한 건 예상이 바뀌고, 두 방식이 나란히 선다", async ({
  page,
}) => {
  const { api, classId } = await newClass(page, "calculator");
  for (const [title, count] of [
    ["요구사항 둘", 2],
    ["요구사항 열둘", 12],
  ] as const) {
    const created = await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
      data: { title, submission_formats: ["repository"] },
    });
    const problemId = (await created.json()).id as number;
    for (let i = 0; i < count; i++) {
      const item = await api.post(`/api/backend/classroom/classes/${classId}/problems/${problemId}/checklist-items`, {
        data: { label: `항목 ${i + 1}`, required: true },
      });
      expect(item.ok()).toBeTruthy();
    }
  }
  await page.goto(`/classes/${classId}/settings#scoring-method`);
  await page.getByTestId("vendor-key-openai-change").click();
  await page.getByTestId("openai-key-input").fill("sk-e2e-test-key-7f2a");
  await page.getByTestId("openai-key-submit").click();
  await expect(page.getByTestId("openai-key-status")).toContainText("연결됨");

  const headline = page.getByTestId("calculator-headline");
  await expect(headline).toContainText("원");
  // 방금 저장한 키가 계산기에도 선다.
  await expect(page.getByTestId("calculator-no-key")).toHaveCount(0);
  await expect(page.getByTestId("calculator-vendor")).toHaveValue("openai");
  await expect(page.getByTestId("calculator-method-single")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("calculator-method-agent")).toBeDisabled();
  await expect(page.getByTestId("calculator-agent-unavailable")).toHaveText("에이전트 Claude 키만");
  await expect(page.getByTestId("calculator-source")).toHaveValue("medium");

  // 칸마다 바꾸면 값이 바뀐다.
  async function changes(act: () => Promise<unknown>) {
    const before = await headline.textContent();
    await act();
    await expect(headline).not.toHaveText(before ?? "");
  }
  await changes(() => page.getByTestId("calculator-source").selectOption("large"));
  await changes(() => page.getByTestId("calculator-problem").selectOption({ label: "요구사항 열둘 · 요구사항 12개" }));
  await changes(() => page.getByTestId("calculator-model").selectOption("gpt-4.1"));

  // 키가 없는 Claude 도 고를 수 있다 — 값이 나오고 「키 없음」이 붙는다. 에이전트가 열린다.
  await changes(() => page.getByTestId("calculator-vendor").selectOption("anthropic"));
  await expect(page.getByTestId("calculator-no-key")).toHaveText("키 없음");
  await expect(page.getByTestId("calculator-unit-price")).toContainText("/ 100만 토큰");
  await page.getByTestId("calculator-method-agent").click();
  await expect(page.getByTestId("calculator-method-agent")).toHaveAttribute("aria-checked", "true");
  await expect(headline).toHaveText("실측 없음");

  await expect(page.getByTestId("compare-cost-single")).toContainText("원");
  await expect(page.getByTestId("compare-cost-agent")).toHaveText("실측 없음");
  await expect(page.getByTestId("compare-time-single")).toHaveText("실측 없음");
  await expect(page.getByTestId("compare-size-single")).toHaveText("모델 한도까지");
  await expect(page.getByTestId("compare-size-agent")).toHaveText("파일을 골라 읽음");
  await expect(page.getByTestId("compare-connections-single")).toHaveText("전부");
  await expect(page.getByTestId("compare-connections-agent")).toHaveText("Claude 키");

  // 좁은 폭에서도 계산기·비교 표가 가로로 넘치지 않는다.
  await page.setViewportSize({ width: 390, height: 900 });
  await expect(page.getByTestId("calculator-compare")).toBeVisible();
  const overflow = await page.evaluate(() => {
    const root = document.documentElement;
    const boxes = ["scoring-calculator", "calculator-compare"].map((id) => {
      const el = document.querySelector<HTMLElement>(`[data-testid=${id}]`)!;
      return el.scrollWidth - el.clientWidth;
    });
    return [root.scrollWidth - root.clientWidth, ...boxes];
  });
  expect(overflow).toEqual([0, 0, 0]);
});
