import { type APIRequestContext, expect, request, test } from "@playwright/test";

import { E2E_OPERATOR_PASSWORD, seedE2eOperator } from "../lib/seed-operator";
import { backendBaseUrl } from "../lib/seed-http";
import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — staged 채점 갈래의 판정 근거(#1283·#1284). 강사 제출 현황의 「판정」에 출처(기계·AI)와 근거 위치가
// 보이고, 충족인데 맞는 인용이 없으면 「의심」이 붙는다.
//
// 채점 갈래는 플랫폼 전체의 운영 설정(`CLASSROOM_SCORING_PIPELINE`)이라 `@exclusive`(일꾼 하나 패스)로 돌고, 끝에
// 지운다. 흉내 저장소(`FakeGitHubAdapter.clone`)는 `app.py` 한 줄 `# fake clone of <url>` 이고, 흉내 채점 어댑터는
// 문구가 처음 나오는 줄을 인용한다 — 그 줄이 주석이라 대조에서 맞지 않고(빈 줄·주석·import 는 근거가 아니다) 「의심」
// 이 된다. 기계 규칙(`path_exists app.py`) 항목은 기계 판정과 그 근거 경로가 보인다.

const SETTING = "/api/operator/runtime-settings/CLASSROOM_SCORING_PIPELINE";
// 의심 재판정(#1285, #1291)은 강사가 클래스 설정에서 고른다 — 흉내 어댑터는 다시 물어도 같은 주석 줄을 인용해
// 「미충족 + 의심 남음」이 된다.

async function operatorRequest(): Promise<APIRequestContext> {
  const su = await seedE2eOperator({ username: `e2e-op-staged-${Date.now()}`, superuser: true });
  // backend 직통 — classroom 조각은 operator 앱을 띄우지 않는다. dev·CI 의 backend 는 도착한 주소를 운영자 Origin 으로 본다.
  const base = backendBaseUrl();
  const ctx = await request.newContext({ baseURL: base, extraHTTPHeaders: { origin: new URL(base).origin } });
  const login = await ctx.post("/api/operator/login", { data: { username: su.username, password: E2E_OPERATOR_PASSWORD } });
  expect(login.ok(), await login.text()).toBeTruthy();
  return ctx;
}

test.describe("staged 판정 근거(#1284)", () => {
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

  test("@exclusive 강사 판정에 출처·근거 위치가 보이고, 맞지 않는 인용의 충족은 의심이 붙는다", async ({ page }) => {
    const seed = `staged-citations-${test.info().workerIndex}-${Date.now()}`;
    const marker = `codemit-e2e-staged-${test.info().workerIndex}-${Date.now()}`;

    await establishClassroomSession(page, seed);
    const api = classroomApi(page);
    const classId = (
      await (
        await api.post("/api/backend/classroom/classes", {
          data: { name: `staged 근거 ${Date.now()}`, instructor_display_name: "강사" },
        })
      ).json()
    ).id as number;
    expect(
      (await api.put(`/api/backend/classroom/classes/${classId}/openai-key`, { data: { api_key: "sk-e2e-test-key" } })).ok(),
    ).toBeTruthy();
    await page.goto(`/classes/${classId}/settings#scoring-method`);
    const escalationSelect = page.getByTestId("escalation-model-select");
    await expect(escalationSelect).toBeEnabled();
    await escalationSelect.selectOption("gpt-5");
    await expect(page.getByTestId("calculator-escalation-model")).toHaveText("gpt-5");
    await page.reload();
    await expect(page.getByTestId("escalation-model-select")).toHaveValue("gpt-5");
    await expect(page.getByTestId("calculator-escalation-rate")).toHaveText("의심 비율 실측 없음");
    const problemId = (
      await (
        await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
          data: { title: "staged", submission_formats: ["repository"] },
        })
      ).json()
    ).id as number;
    const base = `/api/backend/classroom/classes/${classId}/problems/${problemId}`;
    const judged = (await (await api.post(`${base}/checklist-items`, { data: { label: marker, required: true } })).json())
      .id as number;
    const machine = (
      await (
        await api.post(`${base}/checklist-items`, {
          data: { label: "app.py 가 있다", required: true, machine_rule: { kind: "path_exists", path: "app.py" } },
        })
      ).json()
    ).id as number;
    expect((await api.post(`${base}/open`)).ok()).toBeTruthy();
    const joinCode = (await (await api.get(`/api/backend/classroom/classes/${classId}`)).json()).join_code as string;

    await page.context().clearCookies();
    await establishClassroomSession(page, `${seed}-p`);
    await api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "서지우" } });
    const submitted = await api.post(`${base}/submissions`, {
      data: { value: `https://github.com/octocat/${marker}`, submission_format: "repository" },
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
    const verdicts = page.getByTestId(`${row}-verdicts`);
    await expect(verdicts).toContainText("AI 판정");
    await expect(verdicts).toContainText("기계 판정");
    await expect(page.getByTestId(`${row}-citation-${judged}-0`)).toHaveText("app.py:1 — 맞지 않음");
    await expect(page.getByTestId(`${row}-suspect-${judged}`)).toHaveText("의심");
    await expect(page.getByTestId(`${row}-escalated-${judged}`)).toHaveText("올림");
    await expect(verdicts).toContainText("미충족");
    await expect(page.getByTestId(`${row}-evidence-${machine}-0`)).toHaveText("app.py");
    await expect(page.getByTestId(`${row}-suspect-${machine}`)).toHaveCount(0);
  });
});
