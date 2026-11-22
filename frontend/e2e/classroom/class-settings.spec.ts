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

test("채점 비용 예상표 — 빈 클래스에서도 모든 칸에 금액이 있고, 가정을 바꾸면 값이 바뀌며, 감당 크기를 넘기면 보류가 뜬다", async ({
  page,
}) => {
  const { classId } = await newClass(page, "calculator-empty");
  await page.goto(`/classes/${classId}/settings#scoring-method`);
  await page.getByTestId("vendor-key-openai-change").click();
  await page.getByTestId("openai-key-input").fill("sk-e2e-test-key-7f2a");
  await page.getByTestId("openai-key-submit").click();
  await expect(page.getByTestId("openai-key-status")).toContainText("연결됨");

  const table = page.getByTestId("calculator-table");
  await expect(table).toBeVisible();
  // 문제·체크리스트·제출이 0 인 새 클래스 — 「실측 없음」 글자가 없고 모든 모델 행에 금액·감당 글자 수가 있다.
  await expect(page.getByTestId("scoring-calculator")).not.toContainText("실측 없음");
  await expect(page.getByTestId("scoring-calculator")).not.toContainText("모델 한도까지");
  const rows = table.locator("tbody tr[data-testid^=calculator-row-]");
  const count = await rows.count();
  expect(count).toBeGreaterThan(10);
  for (let i = 0; i < count; i++) {
    const row = rows.nth(i);
    await expect(row.locator("[data-testid^=calculator-cost-][data-testid$=-single]")).toContainText("원");
    await expect(row.locator("[data-testid^=calculator-note-][data-testid$=-single]")).toContainText("감당");
  }
  // 에이전트는 Claude 만 — OpenAI 모델은 「지원 안 함」, Claude 모델은 금액이 있다.
  await expect(page.getByTestId("calculator-agent-unsupported-gpt-4.1-mini")).toHaveText("지원 안 함");
  await expect(page.getByTestId("calculator-cost-claude-haiku-5-5-agent")).toContainText("원");
  await expect(page.getByTestId("calculator-no-key-anthropic")).toHaveText("키 없음");
  await expect(page.getByTestId("calculator-no-key-openai")).toHaveCount(0);
  // 지금 클래스의 조합(OpenAI·한 번 호출)이 표시돼 있고, 학기 셈·학생 수·과제 수·재채점 칸은 없다.
  await expect(page.locator("[data-testid^=calculator-cell-][aria-pressed=true]")).toHaveCount(1);
  await expect(page.getByTestId("scoring-calculator")).not.toContainText("학기");
  await expect(page.getByTestId("calculator-students")).toHaveCount(0);
  await expect(page.getByTestId("calculator-assignments")).toHaveCount(0);
  await expect(page.getByTestId("calculator-regrade-rate")).toHaveCount(0);

  // 제출 크기를 감당 크기보다 크게 넣으면 한 번 호출 칸에 「보류」가 뜬다.
  const cost = page.getByTestId("calculator-cost-gpt-4.1-mini-single");
  await page.getByTestId("calculator-source-chars").fill("5000000");
  await page.getByTestId("calculator-source-chars").press("Enter");
  await expect(page.getByTestId("calculator-note-gpt-4.1-mini-single")).toContainText("담지 못함 — 보류");
  await expect(cost).toContainText("0원");

  // 다른 칸을 눌러 고르면 그 칸이 눌린 상태가 된다.
  await page.getByTestId("calculator-cell-claude-haiku-5-5-agent").click();
  await expect(page.getByTestId("calculator-cell-claude-haiku-5-5-agent")).toHaveAttribute("aria-pressed", "true");

  // 방식별 감당 크기는 코드의 숫자다.
  await expect(page.getByTestId("calculator-capacity-agent")).toContainText("zip 100MB · 풀린 크기 256MB · 파일 5만 개 · 시간 300초 × 2회 · 한 건 $1");

  // 좁은 폭에서도 예상표가 가로로 넘치지 않는다.
  await page.setViewportSize({ width: 390, height: 900 });
  await expect(page.getByTestId("calculator-table")).toBeVisible();
  const overflow = await page.evaluate(() => {
    const root = document.documentElement;
    const boxes = ["scoring-calculator", "calculator-table"].map((id) => {
      const el = document.querySelector<HTMLElement>(`[data-testid=${id}]`)!;
      return el.scrollWidth - el.clientWidth;
    });
    return [root.scrollWidth - root.clientWidth, ...boxes];
  });
  expect(overflow).toEqual([0, 0, 0]);
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

  const cost = page.getByTestId("calculator-cost-gpt-4.1-single");
  await expect(cost).toContainText("원");
  await expect(page.getByTestId("calculator-requirements")).toHaveValue("2");
  const before = await cost.textContent();
  await page.getByTestId("calculator-problem").selectOption({ label: "요구사항 열둘 · 항목 12개" });
  await expect(page.getByTestId("calculator-requirements")).toHaveValue("12");
  await expect(cost).not.toHaveText(before ?? "");
  await page.getByTestId("calculator-source").selectOption("p90");
  await expect(page.getByTestId("calculator-source-chars")).toHaveValue("307000");
});
