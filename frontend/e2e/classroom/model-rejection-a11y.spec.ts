import { expect, test } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 모델 거부의 접근성 설명(#1448 ⑤) — 렌더된 컨트롤의 접근성 이름·설명을 본다.
// 거부 상태는 응답 한 칸만 바꿔 만든다(키·모델을 실제로 거부시킬 수 없다).

async function patchJson(page: Page, matches: (pathname: string) => boolean, patch: Record<string, unknown>) {
  await page.route(
    (url) => matches(url.pathname),
    async (route: Route) => {
      if (route.request().method() !== "GET") return route.continue();
      const response = await route.fetch();
      await route.fulfill({ response, json: { ...(await response.json()), ...patch } });
    },
  );
}

async function seedClassAndProblem(page: Page, seed: string) {
  await establishClassroomSession(page, seed);
  const api = classroomApi(page);
  const classId = (
    await (
      await api.post("/api/backend/classroom/classes", {
        data: { name: `모델 거부 ${Date.now()}`, instructor_display_name: "강사" },
      })
    ).json()
  ).id as number;
  expect(
    (await api.put(`/api/backend/classroom/classes/${classId}/openai-key`, { data: { api_key: "sk-e2e-test-key" } })).ok(),
  ).toBeTruthy();
  const problemId = (
    await (
      await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
        data: { title: "거부 문제", submission_formats: ["source"] },
      })
    ).json()
  ).id as number;
  return { classId, problemId };
}

test("문제 편집: 거부된 모델의 select 는 배지만 설명으로 읽고 다시 시도 단추 글자는 섞이지 않는다", async ({ page }) => {
  const { classId, problemId } = await seedClassAndProblem(page, `model-a11y-edit-${test.info().workerIndex}-${Date.now()}`);
  await patchJson(page, (p) => p.startsWith("/api/backend/") && p.endsWith(`/classes/${classId}/problems/${problemId}`), { scoring_model_rejected: true });
  await page.goto(`/classes/${classId}/problems/${problemId}#scoring-model`);

  const target = page.getByRole("combobox", { name: "채점 모델" });
  await expect(target).toHaveAccessibleDescription("모델 거부");
  await expect(page.getByRole("button", { name: "이 모델로 다시 시도" })).toBeVisible();
  await expect(target).not.toHaveAccessibleDescription(/다시 시도/);
});

test("클래스 설정: 저장된 기본 모델이 목록에 없으면 라디오 묶음이 그 줄을 설명으로 읽는다", async ({ page }) => {
  const { classId } = await seedClassAndProblem(page, `model-a11y-settings-${test.info().workerIndex}-${Date.now()}`);
  await patchJson(page, (p) => p.startsWith("/api/backend/") && p.endsWith(`/classroom/classes/${classId}`), { default_model: "retired-model-e2e" });
  await page.goto(`/classes/${classId}/settings#scoring-model`);

  const group = page.getByRole("radiogroup", { name: "기본 모델" });
  await expect(group).toHaveAccessibleDescription("retired-model-e2e 이 연결에서 쓸 수 없음");
});
