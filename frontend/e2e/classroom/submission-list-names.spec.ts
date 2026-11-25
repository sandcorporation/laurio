import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강사의 문제별 제출 목록 — 줄마다 「판정」 단추·「저장소」 링크가 되풀이된다. 낭독기의 단추·링크 목록에서
// 서로 가를 수 있도록 접근성 이름에 누구의 몇 번째 시도인지가 있다(#1478 3). 보이는 글은 그대로다.
test("제출 목록의 「판정」 단추·「저장소」 링크는 이름에 누구의 시도인지를 담는다", async ({ browser }) => {
  test.setTimeout(30_000);
  const seed = `submission-list-names-${test.info().workerIndex}-${Date.now()}`;
  const marker = `codemit-e2e-marker-${test.info().workerIndex}-${Date.now()}`;
  const owner = await browser.newContext();
  const ownerPage = await owner.newPage();
  await establishClassroomSession(ownerPage, seed);
  const api = classroomApi(ownerPage);
  const classId = (
    await (
      await api.post("/api/backend/classroom/classes", {
        data: { name: `제출 목록 이름 ${Date.now()}`, instructor_display_name: "강사" },
      })
    ).json()
  ).id as number;
  expect((await api.put(`/api/backend/classroom/classes/${classId}/openai-key`, { data: { api_key: "sk-e2e-test-key" } })).ok()).toBeTruthy();
  const problemId = (
    await (
      await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
        data: { title: "1주차", submission_formats: ["repository"] },
      })
    ).json()
  ).id as number;
  const base = `/api/backend/classroom/classes/${classId}/problems/${problemId}`;
  await api.post(`${base}/checklist-items`, { data: { label: marker, required: true } });
  await api.post(`${base}/open`);
  const joinCode = (await (await api.get(`/api/backend/classroom/classes/${classId}`)).json()).join_code as string;
  const ownerState = await owner.storageState();
  await owner.close();

  const member = await browser.newContext();
  const memberPage = await member.newPage();
  await establishClassroomSession(memberPage, `${seed}-a`);
  const memberApi = classroomApi(memberPage);
  await memberApi.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "서지우" } });
  const submitted = await memberApi.post(`${base}/submissions`, {
    data: { value: `https://github.com/octocat/${marker}`, submission_format: "repository" },
  });
  expect(submitted.ok()).toBeTruthy();
  const submissionId = (await submitted.json()).id as number;
  // 채점은 요청 밖에서 상주 grader 가 끝낸다 — 「판정」 단추는 채점된 줄에만 있다.
  await expect
    .poll(
      async () => (await (await memberApi.get(`${base}/mine`)).json()).submissions[0]?.status,
      { timeout: 15_000 },
    )
    .toBe("scored");
  await member.close();

  const page = await (await browser.newContext({ storageState: ownerState })).newPage();
  await page.goto(`/classes/${classId}/problems/${problemId}/submissions`);
  const row = page.getByTestId(`instructor-submission-row-${submissionId}`);
  const verdict = row.getByRole("button", { name: /판정.*서지우/ });
  await expect(verdict).toBeVisible();
  await expect(verdict).toHaveText("판정");
  await expect(verdict).toHaveAccessibleName("판정 서지우 시도 1");
  const repository = row.getByRole("link", { name: /저장소.*서지우/ });
  await expect(repository).toHaveText("저장소");
  await expect(repository).toHaveAccessibleName("저장소 서지우 시도 1");
});
