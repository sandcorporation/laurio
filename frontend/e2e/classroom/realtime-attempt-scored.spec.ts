import { expect, test } from "@playwright/test";

import { runInternalScan } from "../lib/seed-http";
import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 참여자 「내 시도」가 새로고침 없이 「채점 완료」로 바뀐다
// (#379, ADR-0046). `scoring-notification.spec.ts`는 화면을 새로 연 뒤(알림
// 링크를 눌러) 판정을 확인하지만, 이 스펙은 **화면을 열어 둔 채로** 채점이
// 끝나는 것을 본다 — `page.reload()`를 어디서도 부르지 않는다는 것 자체가
// 이 스펙의 단언이다.
//
// 이벤트 서비스(SSE)·강의실 BFF의 스트림 중계(버퍼링 없음, 허용목록·Origin
// 검사)까지 실제 요청 하나로 함께 덮는다(ADR-0017 위험 3) — CI 강의실 잡이
// `events` 컨테이너를 `classroom`의 의존성으로 함께 띄운다
// (docker/compose.dev.yaml).
//
// **채점은 dev·CI 에서 큐에 넣는 자리에서 그대로 돈다**(#582, eager) — 키가 있는
// 클래스에 내면 제출 요청 안에서 채점까지 끝나 「채점 중」을 볼 틈이 없다. 그래서
// 키 없이 열어 둔 클래스에 내고(「채점 대기」), 화면을 연 채로 강사가 키를 넣은 뒤
// 스캔을 돌린다 — 스캔이 그 시도를 큐에 넣고 그 자리에서 채점이 끝난다. 강사는 다른
// 브라우저 컨텍스트에 둔다(참여자 화면의 쿠키를 갈아 끼우지 않는다).
test("제출 화면을 연 채로 채점이 끝나면 새로고침 없이 「채점 완료」로 바뀐다", async ({
  page,
  browser,
}) => {
  const seed = `attempt-scored-stream-${test.info().workerIndex}-${Date.now()}`;
  const marker = `codemit-e2e-marker-${test.info().workerIndex}-${Date.now()}`;
  const repositoryUrl = `https://github.com/octocat/${marker}`;

  const instructorContext = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const instructorPage = await instructorContext.newPage();
  await establishClassroomSession(instructorPage, seed);
  const instructorApi = classroomApi(instructorPage);

  const classResponse = await instructorApi.post("/api/backend/classroom/classes", {
    data: { name: `실시간 갱신 테스트 클래스 ${Date.now()}`, instructor_display_name: "강사" },
  });
  expect(classResponse.ok()).toBeTruthy();
  const classId = (await classResponse.json()).id as number;

  const problemResponse = await instructorApi.post(`/api/backend/classroom/classes/${classId}/problems`, {
    data: { title: "1주차", submission_formats: ["repository"] },
  });
  expect(problemResponse.ok()).toBeTruthy();
  const problemId = (await problemResponse.json()).id as number;

  const checklistResponse = await instructorApi.post(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/checklist-items`,
    { data: { label: marker, required: true } },
  );
  expect(checklistResponse.ok()).toBeTruthy();

  const openResponse = await instructorApi.post(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/open`,
  );
  expect(openResponse.ok()).toBeTruthy();

  const classDetailResponse = await instructorApi.get(`/api/backend/classroom/classes/${classId}`);
  const joinCode = (await classDetailResponse.json()).join_code as string;

  await establishClassroomSession(page, `${seed}-participant`);
  const joinResponse = await classroomApi(page).post(`/api/backend/classroom/join/${joinCode}`, {
    data: { display_name: "참여자" },
  });
  expect(joinResponse.ok()).toBeTruthy();

  // 화면을 미리 연다 — 그 뒤로는 화면 안에서만 제출하고 관찰한다.
  await page.goto(`/classes/${classId}/problems/${problemId}/submit`);
  await page.getByTestId("repository-url-input").fill(repositoryUrl);
  await page.getByTestId("submit-repository").click();

  await expect(page.getByTestId("submissions-list")).toBeVisible();
  const row = page.locator('[data-testid^="submission-row-"][data-testid$="-status"]').first();
  await expect(row).toContainText("채점 대기");

  // 화면은 그대로 열어 둔 채로, 강사가 키를 넣고 스캔을 API로 직접 돌린다(#40 — beat 가
  // 이 e2e 잡에 없다).
  const keyResponse = await instructorApi.put(`/api/backend/classroom/classes/${classId}/openai-key`, {
    data: { api_key: "sk-e2e-test-key" },
  });
  expect(keyResponse.ok()).toBeTruthy();
  await instructorContext.close();
  await runInternalScan("classroom-submission-scoring");

  // page.reload()를 호출하지 않는다 — 이벤트 서비스가 attempt-scored를
  // 밀어주고, 화면이 그 신호를 받아 기존 API를 다시 불러 이 값이 바뀐다.
  await expect(row).toContainText("채점 완료", { timeout: 15_000 });
});
