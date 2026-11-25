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
  // 저장하면 폼이 사라진다 — 초점은 「바꾸기」로, 결과는 상태 영역으로(#1447).
  await expect(page.getByTestId("vendor-key-openai-change")).toBeFocused();
  await expect(page.getByRole("status").filter({ hasText: "OpenAI 키를 저장했습니다." })).toBeVisible();
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
  // 저장 뒤 확인 문구가 낭독되고(role=status) 초점이 BODY 로 가지 않는다(#1441-2).
  await expect(page.getByRole("status").filter({ hasText: "기본 모델을 저장했습니다." })).toBeVisible();
  await expect(page.getByTestId("class-default-model-submit")).toBeFocused();

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

test("채점·완성도 검사 방식 — OpenAI 키 클래스의 기본 모델(gpt-4.1-mini)로는 「에이전트」가 꺼진 채 까닭이 툴팁이다(#1311)", async ({
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
    // 까닭은 title 이 아니라 보이는 글이고 선택 그룹이 가리킨다 — 키 까닭이 아니라 모델 까닭이다(#1447).
    const note = page.getByTestId(`${id}-blocked-note`);
    await expect(note).toBeVisible();
    await expect(note).toHaveAttribute("data-reason", "model");
    await expect(note).toContainText("gpt-5-mini 이상");
    await expect(page.getByTestId(`${id}-agent`)).not.toHaveAttribute("title", /.+/);
    await expect(
      page.getByRole("radiogroup", { name: id === "scoring-method" ? "채점 방식" : "완성도 검사 방식" }),
    ).toHaveAccessibleDescription(/gpt-5-mini 이상/);
    await expect(page.getByTestId(`${id}-vendor`)).toHaveText("OpenAI");
  }

  await page.reload();
  await expect(page.getByTestId("scoring-method-single")).toHaveAttribute("aria-checked", "true");
});

test("한 번 호출로 못 담는 제출물 — 고른 값과 에이전트용 모델이 새로고침 뒤에도 남는다(#1311)", async ({ page }) => {
  const { classId } = await newClass(page, "oversize-policy");
  await page.goto(`/classes/${classId}/settings#scoring-method`);
  await page.getByTestId("vendor-key-openai-change").click();
  await page.getByTestId("openai-key-input").fill("sk-e2e-test-key-7f2a");
  await page.getByTestId("openai-key-submit").click();
  await expect(page.getByTestId("openai-key-status")).toContainText("연결됨");

  await expect(page.getByTestId("oversize-policy-reject")).toHaveAttribute("aria-checked", "true");
  await page.getByTestId("oversize-policy-partial").click();
  await expect(page.getByTestId("oversize-policy-partial")).toHaveAttribute("aria-checked", "true");
  await page.reload();
  await expect(page.getByTestId("oversize-policy-partial")).toHaveAttribute("aria-checked", "true");

  await page.getByTestId("oversize-policy-agent").click();
  const model = page.getByTestId("oversize-agent-model");
  await expect(model.locator("option[value='gpt-5-nano']")).toHaveCount(0);
  await model.selectOption("gpt-5-mini");
  await expect(page.getByTestId("oversize-policy-agent")).toHaveAttribute("aria-checked", "true");
  await page.reload();
  await expect(page.getByTestId("oversize-policy-agent")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("oversize-agent-model")).toHaveValue("gpt-5-mini");
});

test("채점 비용 예상표 — 빈 클래스에서도 모든 칸에 금액이 있고, 가정을 바꾸면 값이 바뀌며, 감당 크기를 넘기면 반려가 뜬다", async ({
  page,
}) => {
  const { classId } = await newClass(page, "calculator-empty");
  await page.goto(`/classes/${classId}/settings#scoring-method`);
  await page.getByTestId("vendor-key-openai-change").click();
  await page.getByTestId("openai-key-input").fill("sk-e2e-test-key-7f2a");
  await page.getByTestId("openai-key-submit").click();
  await expect(page.getByTestId("openai-key-status")).toContainText("연결됨");

  // 문제·체크리스트·제출이 0 인 새 클래스 — 드롭다운 셋과 입력 둘로 금액이 나온다.
  const calculator = page.getByTestId("scoring-calculator");
  await expect(calculator).toBeVisible();
  await expect(page.getByTestId("calculator-table")).toHaveCount(0);
  await expect(page.getByTestId("calculator-source-files")).toHaveValue("20");
  await expect(page.getByTestId("calculator-source-chars")).toContainText("3.2만 자");
  await expect(page.getByTestId("calculator-requirements")).toHaveValue("6");
  const amount = page.getByTestId("calculator-amount");
  await expect(amount).toContainText("원");
  await expect(page.getByTestId("calculator-capacity")).toContainText("소스 파일 약");
  await expect(page.getByTestId("calculator-method")).toHaveValue("single");
  for (const word of ["한 학기", "실측", "토큰", "학생 수", "과제 수", "재채점"]) {
    await expect(calculator).not.toContainText(word);
  }

  // 에이전트는 모델마다 — gpt-4.1-mini 에서도 「에이전트」를 고를 수 있고(#1314), 고르면 되는 모델 중 가장 싼 gpt-5-mini 로 바뀌며
  // 목록엔 되는 모델만 남는다(#1311, gpt-5-mini 이상). 「한 번 호출」로 돌리면 모델은 그대로고 목록은 전부다. Claude 로 바꾸면 에이전트 금액이 나온다.
  const method = page.getByTestId("calculator-method");
  const calcModel = page.getByTestId("calculator-model");
  await calcModel.selectOption("gpt-4.1-mini");
  await expect(method.locator("option[value=agent]")).toBeEnabled();
  await method.selectOption("agent");
  await expect(calcModel).toHaveValue("gpt-5-mini");
  await expect(calcModel.locator("option[value='gpt-4.1-mini']")).toHaveCount(0);
  await expect(calcModel.locator("option[value='gpt-5.5']")).toHaveCount(1);
  await method.selectOption("single");
  await expect(calcModel).toHaveValue("gpt-5-mini");
  await expect(calcModel.locator("option[value='gpt-4.1-mini']")).toHaveCount(1);
  await calcModel.selectOption("gpt-4.1-mini");
  await page.getByTestId("calculator-vendor").selectOption("anthropic");
  await expect(page.getByTestId("calculator-vendor")).toContainText("키 없음");
  await page.getByTestId("calculator-method").selectOption("agent");
  await expect(amount).toContainText("원");
  await page.getByTestId("calculator-vendor").selectOption("openai");
  await expect(page.getByTestId("calculator-method")).toHaveValue("single");

  // 소스 파일 수를 바꾸면 글자 수와 금액이 바뀐다.
  const before = await amount.textContent();
  await page.getByTestId("calculator-source-files").fill("100");
  await page.getByTestId("calculator-source-files").press("Enter");
  await expect(page.getByTestId("calculator-source-chars")).toContainText("16만 자");
  await expect(amount).not.toHaveText(before ?? "");

  // 입력한 크기가 고른 모델의 한도를 넘으면 클래스 설정(처음 값 「반려」)대로 금액 자리에 반려가 뜬다.
  await page.getByTestId("calculator-model").selectOption("gpt-4.1-mini");
  await page.getByTestId("calculator-source-files").fill("5000");
  await page.getByTestId("calculator-source-files").press("Enter");
  await expect(amount).toHaveText("담지 못함 — 반려");

  // 좁은 폭에서도 가로로 넘치지 않는다.
  await page.setViewportSize({ width: 390, height: 900 });
  await expect(calculator).toBeVisible();
  const overflow = await page.evaluate(() => {
    const root = document.documentElement;
    const el = document.querySelector<HTMLElement>("[data-testid=scoring-calculator]")!;
    return [root.scrollWidth - root.clientWidth, el.scrollWidth - el.clientWidth];
  });
  expect(overflow).toEqual([0, 0]);
});

test("채점 비용 예상표 — 문제가 있으면 그 문제의 항목 수가 기본값을 대신하고 고르면 바뀐다", async ({ page }) => {
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

  const cost = page.getByTestId("calculator-amount");
  await expect(cost).toContainText("원");
  await expect(page.getByTestId("calculator-requirements")).toHaveValue("2");
  const before = await cost.textContent();
  await page.getByTestId("calculator-problem").selectOption({ label: "요구사항 열둘 · 항목 12개" });
  await expect(page.getByTestId("calculator-requirements")).toHaveValue("12");
  await expect(cost).not.toHaveText(before ?? "");
});

test("채점 키 지우기는 줄 안에서 한 번 더 묻는다 — 브라우저 확인 창이 아니고 Esc 로 닫힌다(#1400)", async ({ page }) => {
  const { api, classId } = await newClass(page, "delete-key");
  const key = await api.put(`/api/backend/classroom/classes/${classId}/openai-key`, {
    data: { api_key: "sk-e2e-test-key-7f2a" },
  });
  expect(key.ok()).toBeTruthy();
  let dialogs = 0;
  page.on("dialog", (dialog) => {
    dialogs += 1;
    void dialog.dismiss();
  });
  await page.goto(`/classes/${classId}/settings#scoring-key`);

  const trigger = page.getByTestId("vendor-key-openai-delete");
  const confirm = page.getByTestId("vendor-key-openai-delete-confirm");
  await trigger.click();
  await expect(confirm).toContainText("채점이 멈춥니다");
  await expect(confirm.getByRole("button", { name: "그대로 두기" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(confirm).toHaveCount(0);
  await expect(trigger).toBeFocused();

  await trigger.click();
  await page.getByTestId("vendor-key-openai-delete-confirm-button").click();
  await expect(page.getByTestId("openai-key-status")).toContainText("연결 없음");
  await expect(trigger).toHaveCount(0);
  await expect(page.getByTestId("vendor-key-openai-change")).toBeFocused();
  expect(dialogs).toBe(0);
});

test("채점 키 입력칸 — 확인 결과·저장 오류가 칸에 연결되고 확정 오류에만 aria-invalid 가 붙는다(#1447)", async ({ page }) => {
  const { classId } = await newClass(page, "key-describe");
  await page.route("https://api.openai.com/v1/models", (route) => route.fulfill({ status: 401, body: "{}" }));
  await page.goto(`/classes/${classId}/settings#scoring-key`);
  await page.getByTestId("vendor-key-openai-change").click();
  const input = page.getByTestId("openai-key-input");
  const live = page.getByRole("status").filter({ hasText: "이 키는 쓸 수 없습니다" });
  await expect(input).not.toHaveAttribute("aria-invalid", "true");
  await input.fill("sk-e2e-bad-key-0000");
  await expect(live).toBeVisible();
  await expect(input).toHaveAccessibleDescription(/이 키는 쓸 수 없습니다/);
  await expect(input).toHaveAttribute("aria-invalid", "true");
});

test("기한 순서 — 권장 기한이 마감보다 늦으면 문구가 보이고 날짜·시각 칸이 그것을 가리킨다(#1447)", async ({ page }) => {
  const { classId } = await newClass(page, "due-order");
  await page.goto(`/classes/${classId}/problems/new`);
  await page.getByTestId("new-problem-recommended-due-date").fill("2030-05-10");
  await page.getByTestId("new-problem-due-date").fill("2030-05-01");
  await page.getByTestId("new-problem-title-input").fill("기한 순서 시험");
  await page.getByTestId("new-problem-submit").click();
  await expect(page.getByRole("alert").filter({ hasText: "권장 기한이 마감보다 늦습니다" })).toBeVisible();
  for (const id of ["new-problem-recommended-due-date", "new-problem-recommended-due-time", "new-problem-due-date", "new-problem-due-time"]) {
    await expect(page.getByTestId(id)).toHaveAccessibleDescription(/권장 기한이 마감보다 늦습니다/);
    await expect(page.getByTestId(id)).toHaveAttribute("aria-invalid", "true");
  }
});

test("호환 서버 저장 — 초점이 연결 상태로 가고 저장 결과가 상태 영역에 읽히며, 다시 열면 옛 결과가 비워진다(#1447)", async ({ page }) => {
  const { api, classId } = await newClass(page, "compat-save");
  const current = await (await api.get(`/api/backend/classroom/classes/${classId}`)).json();
  await page.route(`**/classes/${classId}/compatible-server`, (route) =>
    route.request().method() === "PUT" ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(current) }) : route.fallback(),
  );
  await page.goto(`/classes/${classId}/settings#scoring-key`);
  await page.getByTestId("scoring-connection-kind-compatible_server").click();
  await page.getByTestId("scoring-server-url-input").fill("https://llm.example.test/v1");
  await page.getByTestId("scoring-server-submit").click();

  await expect(page.getByTestId("scoring-server-url-input")).toHaveCount(0);
  await expect(page.getByRole("status").filter({ hasText: "호환 서버를 저장했습니다." })).toBeVisible();
  await expect(page.getByTestId("scoring-connection-focus")).toBeFocused();

  // 다른 동작을 시작하면 옛 결과를 비운다 — 낭독기가 다시 읽지 않게.
  await page.getByTestId("vendor-key-openai-change").click();
  await expect(page.getByTestId("scoring-connection-notice")).toBeEmpty();
});

test("기한 순서를 서버가 거절해도 문구는 기한 카드의 alert 하나뿐이다 — 새 문제·문제 편집(#1447)", async ({ page }) => {
  const { api, classId } = await newClass(page, "due-422");
  const refuse = (route: import("@playwright/test").Route) =>
    route.request().method() === "POST" || route.request().method() === "PATCH" || route.request().method() === "PUT"
      ? route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "권장 기한은 마감보다 늦을 수 없습니다." }) })
      : route.fallback();
  const dueAlerts = page.getByRole("alert").filter({ hasText: /권장 기한(은|이) 마감보다 늦/ });

  await page.route(`**/classes/${classId}/problems`, refuse);
  await page.goto(`/classes/${classId}/problems/new`);
  await page.getByTestId("new-problem-title-input").fill("서버 거절");
  await page.getByTestId("new-problem-submit").click();
  await expect(dueAlerts).toHaveCount(1);
  await expect(page.getByTestId("new-problem-due-order-note")).toBeVisible();
  await expect(page.getByTestId("new-problem-error")).toHaveCount(0);
  await page.unroute(`**/classes/${classId}/problems`, refuse);

  const created = await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
    data: { title: "편집 거절", submission_formats: ["source"], checklist_items: [{ label: "합을 출력한다", required: true }] },
  });
  const problemId = (await created.json()).id as number;
  await page.route(`**/classes/${classId}/problems/${problemId}`, refuse);
  await page.goto(`/classes/${classId}/problems/${problemId}`);
  await page.getByTestId("edit-problem-title-input").fill("편집 거절 2");
  await page.getByTestId("edit-problem-submit").click();
  await expect(dueAlerts).toHaveCount(1);
  await expect(page.getByTestId("edit-problem-due-order-note")).toBeVisible();
  await expect(page.getByTestId("edit-problem-error-message")).toHaveCount(0);
});

test("호환 서버 주소 — 브라우저 풍선 없이 앱 문장으로 거절하고 칸에 연결하며, 빠진 https:// 는 채워 보낸다(#1455)", async ({ page }) => {
  const { api, classId } = await newClass(page, "compat-url");
  const current = await (await api.get(`/api/backend/classroom/classes/${classId}`)).json();
  let sentUrl = "";
  await page.route(`**/classes/${classId}/compatible-server`, (route) => {
    if (route.request().method() !== "PUT") return route.fallback();
    sentUrl = route.request().postDataJSON().server_url;
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(current) });
  });
  await page.goto(`/classes/${classId}/settings#scoring-key`);
  await page.getByTestId("scoring-connection-kind-compatible_server").click();
  const url = page.getByTestId("scoring-server-url-input");
  await url.fill("not a url");
  await page.getByTestId("scoring-server-submit").click();
  await expect(page.getByRole("alert").filter({ hasText: "https://llm.example.com/v1 꼴로" })).toBeVisible();
  await expect(url).toHaveAttribute("aria-invalid", "true");
  await expect(url).toHaveAccessibleDescription(/꼴로 넣어 주세요/);
  expect(sentUrl).toBe("");

  await url.fill("llm.example.test/v1");
  await page.getByTestId("scoring-server-submit").click();
  await expect(page.getByRole("status").filter({ hasText: "호환 서버를 저장했습니다." })).toBeVisible();
  expect(sentUrl).toBe("https://llm.example.test/v1");
});
