import { expect, test, type Page } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 완성도(#883, ADR-0072): 강사 제출 현황의 「완성도 채점」 → 비용 확인 → 순위 표, 그리고 공개를 켠
// 참여자의 본인 완성도. 결정적 채점은 fake 어댑터다 — 체크리스트 문구가 저장소 URL(= fake clone 소스)에 있으면
// 판정은 충족, 완성도는 5, 없으면 1. 준비는 API 로 한다.

type Seeded = { classId: number; problemId: number; base: string };

async function seed(page: Page, name: string, participants: { name: string; suffix: string }[]): Promise<Seeded> {
  const marker = `codemit-quality-${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, name);
  const api = classroomApi(page);
  const classId = (
    await (
      await api.post("/api/backend/classroom/classes", {
        data: { name: `완성도 ${Date.now()}`, instructor_display_name: "강사" },
      })
    ).json()
  ).id as number;
  expect(
    (await api.put(`/api/backend/classroom/classes/${classId}/openai-key`, { data: { api_key: "sk-e2e-test-key" } })).ok(),
  ).toBeTruthy();
  const problemId = (
    await (
      await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
        data: { title: "1주차", submission_formats: ["repository"] },
      })
    ).json()
  ).id as number;
  const base = `/api/backend/classroom/classes/${classId}/problems/${problemId}`;
  await api.post(`${base}/checklist-items`, { data: { label: marker, required: true } });
  await api.post(`${base}/checklist-items`, { data: { label: `${marker}-extra`, required: false } });
  await api.post(`${base}/open`);
  const joinCode = (await (await api.get(`/api/backend/classroom/classes/${classId}`)).json()).join_code as string;

  for (const person of participants) {
    await page.context().clearCookies();
    await establishClassroomSession(page, `${name}-${person.suffix}`);
    await api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: person.name } });
    const r = await api.post(`${base}/submissions`, {
      data: { value: `https://github.com/octocat/${marker}-${person.suffix}`, submission_format: "repository" },
    });
    expect(r.ok()).toBeTruthy();
  }
  await page.context().clearCookies();
  await establishClassroomSession(page, name);
  // 판정이 모두 끝나 통과한 사람이 생길 때까지.
  await expect
    .poll(
      async () =>
        ((await (await api.get(`${base}/submissions`)).json()) as { status: string }[]).every((s) => s.status === "scored"),
      { timeout: 1_500 },
    )
    .toBe(true);
  return { classId, problemId, base };
}

// 시험 하나 3초 한도 — 준비(가입·제출·판정)는 beforeAll 이 따로 한다. 둘째 시험은 첫째가 매긴 결과를 본다.
test.describe.serial("완성도", () => {
  const name = `quality-${Date.now()}`;
  let seeded: Seeded;

  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    // 「extra」를 URL 에 담은 사람은 선택 항목도 5 — 가람 15/15, 나래 11/15.
    seeded = await seed(page, name, [
      { name: "가람", suffix: "extra" },
      { name: "나래", suffix: "b" },
    ]);
    await context.close();
  });

  test("완성도 채점: 버튼 → 비용 확인 → 순위 표·근거", async ({ page }) => {
    await establishClassroomSession(page, name);
    await page.goto(`/classes/${seeded.classId}/problems/${seeded.problemId}/submissions`);

    await page.getByTestId("quality-run-button").click();
    await expect(page.getByTestId("quality-confirm-line")).toContainText("새로 채점할 2명");
    await page.getByTestId("quality-confirm-run").click();

    const list = page.getByTestId("quality-list");
    await expect(list.locator(":scope > li")).toHaveCount(2);
    const first = list.locator(":scope > li").first();
    await expect(first).toContainText("1등");
    await expect(first).toContainText("가람");
    await expect(first).toContainText("100.0");
    await expect(list.locator(":scope > li").nth(1)).toContainText("73.3");

    await first.getByRole("button", { name: "근거" }).click();
    await expect(first.locator('[data-testid$="-reasons"]')).toContainText("5/5");

    // 다시 누르면 할 일이 없다.
    await page.getByTestId("quality-run-button").click();
    await expect(page.getByTestId("quality-confirm-line")).toHaveText("새로 채점할 사람이 없습니다");
  });

  test("완성도 공개: 켜면 참여자는 자기 등수만 본다", async ({ page }) => {
    await establishClassroomSession(page, name);
    await page.goto(`/classes/${seeded.classId}/problems/${seeded.problemId}/submissions`);
    await page.getByTestId("quality-public-switch").check();
    await expect(page.getByTestId("quality-public-switch")).toBeChecked();

    await page.context().clearCookies();
    await establishClassroomSession(page, `${name}-b`);
    await page.goto(`/classes/${seeded.classId}/problems/${seeded.problemId}/submit`);
    await expect(page.getByTestId("my-quality-rank")).toHaveText("완성도 순위 2등 / 2명");
    await expect(page.getByText("가람")).toHaveCount(0);
  });
});
