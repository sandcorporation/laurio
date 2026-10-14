import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 참여자 문제 목록(#639, 시안 v2 Mine). 머리의 진행 한 줄(n/m 통과 · 채점 중 a · 미제출 b),
// 한 줄 행(시도 k회 · 마지막 …, 배지 하나, 행 전체가 링크), 접힌 「숨겨진 문제 N」을 본다.
// 통과·미통과 낱말은 백엔드 시험(test_classroom_my_problems_progress.py)이 맡는다 — 채점은 상주
// grader 라 여기서 「채점 중」을 붙들 수 없어, 키 없는 클래스로 「채점 대기」를 만든다.
test("참여자 문제 목록이 진행 한 줄과 한 줄 행으로 보인다", async ({ page, browser }) => {
  const seed = `participant-list-${test.info().workerIndex}-${Date.now()}`;

  const instructorContext = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const instructorPage = await instructorContext.newPage();
  await establishClassroomSession(instructorPage, seed);
  const api = classroomApi(instructorPage);

  const classId = (
    await (
      await api.post("/api/backend/classroom/classes", {
        data: { name: `목록 테스트 ${Date.now()}`, instructor_display_name: "강사" },
      })
    ).json()
  ).id as number;
  const base = `/api/backend/classroom/classes/${classId}`;

  async function openProblem(title: string): Promise<number> {
    const created = await api.post(`${base}/problems`, {
      data: { title, submission_formats: ["repository"] },
    });
    expect(created.ok()).toBeTruthy();
    const id = (await created.json()).id as number;
    const item = await api.post(`${base}/problems/${id}/checklist-items`, {
      data: { label: "통과 조건", required: true },
    });
    expect(item.ok()).toBeTruthy();
    expect((await api.post(`${base}/problems/${id}/open`)).ok()).toBeTruthy();
    return id;
  }
  const waiting = await openProblem("제출한 문제");
  const untouched = await openProblem("안 낸 문제");
  const hidden = await openProblem("숨길 문제");

  const joinCode = (await (await api.get(base)).json()).join_code as string;
  await establishClassroomSession(page, `${seed}-participant`);
  const participantApi = classroomApi(page);
  expect(
    (await participantApi.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "서지우" } })).ok(),
  ).toBeTruthy();
  for (const id of [waiting, hidden]) {
    const submitted = await participantApi.post(`${base}/problems/${id}/submissions`, {
      data: { value: `https://github.com/octocat/e2e-${id}`, submission_format: "repository" },
    });
    expect(submitted.ok()).toBeTruthy();
  }
  expect((await api.post(`${base}/problems/${hidden}/hide`)).ok()).toBeTruthy();

  await page.goto(`/classes/${classId}/problems/mine`);

  await expect(page.getByTestId("my-problems-progress-count")).toHaveText("0/2 통과");
  await expect(page.getByTestId("my-problems-progress-rest")).toHaveText("채점 중 1 · 미제출 1");
  await expect(page.getByTestId(`my-problem-row-${waiting}-status`)).toHaveText("채점 중");
  await expect(page.getByTestId(`my-problem-row-${waiting}-attempts`)).toContainText("시도 1회 · 마지막");
  await expect(page.getByTestId(`my-problem-row-${untouched}-status`)).toHaveText("미제출");
  await expect(page.getByTestId(`my-problem-row-${untouched}-attempts`)).toHaveCount(0);

  const toggle = page.getByTestId("hidden-problems-toggle");
  await expect(toggle).toHaveText(/숨겨진 문제 1/);
  await expect(page.getByTestId("hidden-problems-list")).toHaveCount(0);
  await toggle.click();
  await expect(page.getByTestId(`my-problem-row-${hidden}-status`)).toHaveText("채점 중");

  await page.getByTestId(`my-problem-row-${untouched}-link`).click();
  await expect(page).toHaveURL(new RegExp(`/problems/${untouched}/submit$`));
});
