import { expect, test } from "@playwright/test";

import { runSeed } from "../lib/seed-http";
import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 「최근 제출」의 「전체」 → 「제출」 화면, 「채점 실패」 시도의 「다시 채점」(#1317). 확인 창을 거쳐 걸면
// 상주 grader 가 정정을 돌리고 화면이 신호로 다시 읽으며, 새로고침해도 그 줄은 정정된 판정(통과)이고 버튼이 없다.
// 「채점 실패」 점수는 흉내 채점기가 내지 않으므로 키 없이 낸 시도(채점 대기)에 시드로 심고, 그 뒤에 키를 넣는다 —
// 정정은 키가 있어야 돈다. 체크리스트 문구를 저장소 URL 에 심어 두면 흉내 채점기가 통과시킨다.
test("제출 화면: 「채점 실패」 줄만 「다시 채점」, 확인 창을 거쳐 걸면 새로고침 뒤 정정된 판정이다", async ({ page }) => {
  const seed = `class-attempts-regrade-${test.info().workerIndex}-${Date.now()}`;
  const marker = `codemit-e2e-marker-${test.info().workerIndex}-${Date.now()}`;

  await establishClassroomSession(page, seed);
  const api = classroomApi(page);

  const classId = (
    await (
      await api.post("/api/backend/classroom/classes", {
        data: { name: `다시 채점 ${Date.now()}`, instructor_display_name: "강사" },
      })
    ).json()
  ).id as number;
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

  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-a`);
  await api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "서지우" } });
  const submitted = await api.post(`${base}/submissions`, {
    data: { value: `https://github.com/octocat/${marker}`, submission_format: "repository" },
  });
  expect(submitted.ok()).toBeTruthy();
  const submissionId = (await submitted.json()).id as number;
  await runSeed("classroom-failed-score", { submission_id: submissionId });

  await page.context().clearCookies();
  await establishClassroomSession(page, seed);
  expect(
    (await api.put(`/api/backend/classroom/classes/${classId}/openai-key`, { data: { api_key: "sk-e2e-test-key" } })).ok(),
  ).toBeTruthy();

  await page.goto(`/classes/${classId}`);
  await page.getByTestId("recent-attempts-all").click();
  await expect(page.getByTestId("class-attempts-heading")).toHaveText("제출");
  const row = page.getByTestId(`class-attempt-${submissionId}`);
  await expect(row).toContainText("서지우");
  await expect(row).toContainText("채점 실패");

  await page.getByTestId(`regrade-${submissionId}`).click();
  const dialog = page.getByTestId("regrade-dialog");
  await expect(dialog).toContainText("서지우 · 1주차");
  await expect(page.getByTestId("regrade-amount")).toContainText("원");
  await page.getByTestId("regrade-confirm").click();
  await expect(dialog).toBeHidden();

  // 정정이 끝나면 grader 가 attempt-scored 를 내고 화면이 다시 읽는다 — 그다음 새로고침해도 그대로다.
  await expect(page.getByTestId(`regrade-${submissionId}`)).toHaveCount(0);
  await expect(row).not.toContainText("채점 실패");
  await page.reload();
  await expect(row).toContainText("통과");
  await expect(row).not.toContainText("채점 실패");
  await expect(page.getByTestId(`regrade-${submissionId}`)).toHaveCount(0);
});
