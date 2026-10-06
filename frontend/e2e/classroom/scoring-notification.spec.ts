import { expect, test } from "@playwright/test";

import { drainClassroomScoringScan } from "../lib/seed-http";
import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 채점이 끝나면 알림이 오고, 그 알림을 누르면 그 시도로 간다
// (#303, #329, #340, ADR-0043).
//
// 이 스펙 전까지는 이 흐름 전체를 CI e2e로도, 에이전트의 브라우저 걷기로도
// 확인할 수 없었다(#340) — 강의실 채점이 항상 실물 OpenAI 어댑터를 강사 키로
// 직접 불렀기 때문이다. `CLASSROOM_SCORING_ADAPTER_MODE` 기본값(fake)이
// `FakeClassroomScoringAdapter`로 네트워크 없이 결정적으로 채점을 끝내면서
// (ADR-0043) 이 스펙이 비로소 가능해졌다.
//
// 결정성의 근거: `FakeClassroomScoringAdapter`는 체크리스트 문구가 제출된
// 소스에 그대로 등장하는지를 본다. 저장소 형식 제출은 dev/CI에서
// `core.repository_adapters.FakeGitHubAdapter.clone`이 항상
// `"# fake clone of {url}\n"`을 소스로 돌려주므로, 체크리스트 문구를 그 URL의
// 일부로 심으면 통과가 결정적으로 보장된다 — 스토리지에 파일을 직접 써야 하는
// source 형식보다 준비가 가볍다.
//
// 준비 단계는 시임 규약(ADR-0017/0021)대로 `classroomApi`로 백엔드 API를
// 직접 친다 — 화면으로 클래스·문제·체크리스트를 만드는 것은 각자의 전용
// 스펙(problem-templates.spec.ts 등)이 이미 덮는다. 스캔도 화면이 아니라
// `drainClassroomScoringScan`으로 직접 돌린다(#40 — celery가 이 e2e 잡에 없다).

test("채점이 끝나면 알림이 오고, 그 알림을 누르면 그 시도로 간다", async ({ page }) => {
  const seed = `scoring-notification-${test.info().workerIndex}-${Date.now()}`;
  const marker = `codemit-e2e-marker-${test.info().workerIndex}-${Date.now()}`;
  const repositoryUrl = `https://github.com/octocat/${marker}`;

  await establishClassroomSession(page, seed);
  const api = classroomApi(page);

  const classResponse = await api.post("/api/backend/classroom/classes", {
    data: { name: `채점 알림 테스트 클래스 ${Date.now()}`, instructor_display_name: "강사" },
  });
  expect(classResponse.ok()).toBeTruthy();
  const classId = (await classResponse.json()).id as number;

  // fake 경로도 "키가 있어야 채점 후보에 든다"는 규칙은 그대로 지킨다(ADR-0043)
  // — 값 자체은 네트워크로 나가지 않으므로 아무 문자열이나 된다.
  const keyResponse = await api.put(`/api/backend/classroom/classes/${classId}/openai-key`, {
    data: { api_key: "sk-e2e-test-key" },
  });
  expect(keyResponse.ok()).toBeTruthy();

  const problemResponse = await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
    data: { title: "1주차", submission_formats: ["repository"] },
  });
  expect(problemResponse.ok()).toBeTruthy();
  const problemId = (await problemResponse.json()).id as number;

  const checklistResponse = await api.post(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/checklist-items`,
    { data: { label: marker, required: true } },
  );
  expect(checklistResponse.ok()).toBeTruthy();

  const openResponse = await api.post(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/open`,
  );
  expect(openResponse.ok()).toBeTruthy();

  const classDetailResponse = await api.get(`/api/backend/classroom/classes/${classId}`);
  const joinCode = (await classDetailResponse.json()).join_code as string;

  // 참여자로 갈아탄다 — 알림은 언제나 낸 사람에게 가고 강사에게는 가지 않는다
  // (classroom/scoring.py `_notify_submitter_of_score`).
  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-participant`);
  const joinResponse = await api.post(`/api/backend/classroom/join/${joinCode}`, {
    data: { display_name: "참여자" },
  });
  expect(joinResponse.ok()).toBeTruthy();

  const submitResponse = await api.post(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/submissions`,
    { data: { value: repositoryUrl, submission_format: "repository" } },
  );
  expect(submitResponse.ok()).toBeTruthy();
  const submissionId = (await submitResponse.json()).id as number;

  await drainClassroomScoringScan();

  await page.goto("/notifications");
  await expect(page.getByTestId("notifications-heading")).toBeVisible();

  const notificationLink = page.locator(`a[href*="#submission-${submissionId}"]`);
  await expect(notificationLink).toBeVisible();
  await expect(notificationLink).toContainText("통과");

  await notificationLink.click();

  await expect(page).toHaveURL(
    new RegExp(`/classes/${classId}/problems/${problemId}/submit#submission-${submissionId}$`),
  );
  await expect(page.getByTestId(`submission-row-${submissionId}-status`)).toContainText(
    "채점 완료 · 통과",
  );
  await expect(page.getByTestId(`submission-row-${submissionId}-verdicts`)).toContainText("충족");
});
