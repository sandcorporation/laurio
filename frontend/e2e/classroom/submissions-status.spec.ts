import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 강사의 제출 현황(#638, 시안 v2): 통계 바(통과 n/N · 시도), 참여자별 최신 시도
// 한 줄, 「판정」 펼치기, 「모든 시도」, 아직 내지 않은 참여자 수와 참여자 탭 링크.
// 결정적 채점의 근거는 scoring-notification.spec.ts 머리에 있다 — 체크리스트 문구를 저장소
// URL 에 심으면 fake 어댑터가 통과시킨다. 준비는 API 로 한다.
test("제출 현황: 통계 바·참여자별 최신 시도·판정 펼치기·안 낸 사람 수", async ({ page }) => {
  const seed = `submissions-status-${test.info().workerIndex}-${Date.now()}`;
  const marker = `codemit-e2e-marker-${test.info().workerIndex}-${Date.now()}`;

  await establishClassroomSession(page, seed);
  const api = classroomApi(page);

  const classId = (
    await (
      await api.post("/api/backend/classroom/classes", {
        data: { name: `제출 현황 ${Date.now()}`, instructor_display_name: "강사" },
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
  await api.post(`${base}/open`);
  const joinCode = (await (await api.get(`/api/backend/classroom/classes/${classId}`)).json()).join_code as string;

  // 참여자 둘 — 하나는 두 번 내고(통과), 하나는 가입만 한다.
  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-a`);
  await api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "서지우" } });
  for (const n of [1, 2]) {
    const r = await api.post(`${base}/submissions`, {
      data: { value: `https://github.com/octocat/${marker}-${n}`, submission_format: "repository" },
    });
    expect(r.ok()).toBeTruthy();
  }
  await expect
    .poll(async () => (await (await api.get(`${base}/mine`)).json()).submissions.every((s: { status: string }) => s.status === "scored"), {
      timeout: 2_500,
    })
    .toBe(true);
  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-b`);
  await api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "한도현" } });

  await page.context().clearCookies();
  await establishClassroomSession(page, seed);
  await page.goto(`/classes/${classId}/problems/${problemId}/submissions`);

  await expect(page.getByTestId("submissions-stat-passed")).toContainText("1/2");
  await expect(page.getByTestId("submissions-stat-attempts")).toContainText("2");
  // 최신 시도 한 줄 — 두 번째 시도.
  const list = page.getByTestId("problem-submissions-list");
  await expect(list.locator(":scope > li")).toHaveCount(1);
  await expect(list).toContainText("서지우");
  await expect(list).toContainText("시도 2");
  await expect(list).toContainText("필수 2/2");

  await list.getByRole("button", { name: "판정" }).click();
  await expect(list.locator('[data-testid$="-verdicts"]')).toBeVisible();

  await expect(page.getByTestId("submissions-sort")).toHaveText("정렬: 최근 제출순");

  await page.getByTestId("submissions-view-all").click();
  await expect(list.locator(":scope > li")).toHaveCount(2);
  await expect(page.getByTestId("submissions-sort")).toHaveCount(0);

  await expect(page.getByTestId("submissions-not-submitted")).toContainText("아직 내지 않은 참여자 1명");
  await expect(page.getByTestId("submissions-not-submitted-link")).toHaveAttribute(
    "href",
    `/classes/${classId}?tab=participants`,
  );
});
