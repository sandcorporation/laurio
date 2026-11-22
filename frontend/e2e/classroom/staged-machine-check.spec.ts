import { type APIRequestContext, expect, request, test } from "@playwright/test";

import { E2E_OPERATOR_PASSWORD, seedE2eOperator } from "../lib/seed-operator";
import { backendBaseUrl } from "../lib/seed-http";
import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — staged 의 「기계 확인 완료」·「AI 판정 필요」(#1294). 기계 규칙이 있는 항목은 문제 편집의 항목 줄에
// 「기계 확인」 배지가 붙는다. 판정에서 기계 충족은 「기계 판정」으로 확정되고, 기계 미충족은 모델(흉내 어댑터)에게
// 넘어가 「AI 판정」이 되며 그 배지의 툴팁이 기계 메모다.
//
// 채점 갈래는 플랫폼 전체의 운영 설정이라 `@exclusive` 로 돌고 끝에 지운다. 흉내 저장소는 `app.py` 하나뿐이라
// `README*` 규칙은 미충족이다.

const SETTING = "/api/operator/runtime-settings/CLASSROOM_SCORING_PIPELINE";
const NOTE = "기계 확인: 경로 `README*` 에 맞는 파일이 소스에 없다.";

async function operatorRequest(): Promise<APIRequestContext> {
  const su = await seedE2eOperator({ username: `e2e-op-machine-${Date.now()}`, superuser: true });
  const base = backendBaseUrl();
  const ctx = await request.newContext({ baseURL: base, extraHTTPHeaders: { origin: new URL(base).origin } });
  const login = await ctx.post("/api/operator/login", { data: { username: su.username, password: E2E_OPERATOR_PASSWORD } });
  expect(login.ok(), await login.text()).toBeTruthy();
  return ctx;
}

test.describe("staged 기계 확인(#1294)", () => {
  let operator: APIRequestContext;

  test.beforeAll(async () => {
    operator = await operatorRequest();
    const saved = await operator.post(SETTING, { data: { value: "staged" } });
    expect(saved.ok(), await saved.text()).toBeTruthy();
  });

  test.afterAll(async () => {
    await operator.post(`${SETTING}/clear`, { data: {} });
    await operator.dispose();
  });

  test("@exclusive 기계 확인 배지가 붙고, 기계 미충족은 AI 판정에 기계 메모 툴팁으로 남는다", async ({ page }) => {
    const seed = `staged-machine-${test.info().workerIndex}-${Date.now()}`;

    await establishClassroomSession(page, seed);
    const api = classroomApi(page);
    const classId = (
      await (
        await api.post("/api/backend/classroom/classes", {
          data: { name: `기계 확인 ${Date.now()}`, instructor_display_name: "강사" },
        })
      ).json()
    ).id as number;
    expect(
      (await api.put(`/api/backend/classroom/classes/${classId}/openai-key`, { data: { api_key: "sk-e2e-test-key" } })).ok(),
    ).toBeTruthy();
    const problemId = (
      await (
        await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
          data: { title: "기계 확인", submission_formats: ["repository"] },
        })
      ).json()
    ).id as number;
    const base = `/api/backend/classroom/classes/${classId}/problems/${problemId}`;
    const addItem = async (data: Record<string, unknown>) =>
      (await (await api.post(`${base}/checklist-items`, { data: { required: true, ...data } })).json()).id as number;
    const confirmed = await addItem({ label: "app.py 가 있다", machine_rule: { kind: "path_exists", path: "app.py" } });
    const unmet = await addItem({ label: "README 가 있다", machine_rule: { kind: "path_exists", path: "README*" } });
    const judged = await addItem({ label: "함수 이름이 뜻을 드러낸다" });

    await page.goto(`/classes/${classId}/problems/${problemId}`);
    await expect(page.getByTestId(`checklist-item-${confirmed}-machine-badge`)).toHaveText("기계 확인");
    await expect(page.getByTestId(`checklist-item-${unmet}-machine-badge`)).toHaveText("기계 확인");
    await expect(page.getByTestId(`checklist-item-${judged}-machine-badge`)).toHaveCount(0);

    expect((await api.post(`${base}/open`)).ok()).toBeTruthy();
    const joinCode = (await (await api.get(`/api/backend/classroom/classes/${classId}`)).json()).join_code as string;

    await page.context().clearCookies();
    await establishClassroomSession(page, `${seed}-p`);
    await api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "서지우" } });
    const submitted = await api.post(`${base}/submissions`, {
      data: { value: `https://github.com/octocat/${seed}`, submission_format: "repository" },
    });
    expect(submitted.ok()).toBeTruthy();
    const submissionId = (await submitted.json()).id as number;
    await expect
      .poll(async () => (await (await api.get(`${base}/mine`)).json()).submissions[0]?.status, { timeout: 2_500 })
      .toBe("scored");

    await page.context().clearCookies();
    await establishClassroomSession(page, seed);
    await page.goto(`/classes/${classId}/problems/${problemId}/submissions`);
    const row = `instructor-submission-row-${submissionId}`;
    await page.getByTestId(`${row}-verdict-toggle`).click();
    await expect(page.getByTestId(`${row}-source-${confirmed}`)).toHaveText("기계 판정");
    await expect(page.getByTestId(`${row}-source-${unmet}`)).toHaveText("AI 판정");
    await expect(page.getByTestId(`${row}-source-${unmet}`)).toHaveAttribute("title", NOTE);
    await expect(page.getByTestId(`${row}-source-${judged}`)).toHaveText("AI 판정");
    await expect(page.getByTestId(`${row}-source-${judged}`)).not.toHaveAttribute("title", /.+/);
  });
});
