import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 보관된 클래스는 읽기 전용이다 (#438/#439, spec #432).
//
// 백엔드 pytest가 판정 로직(어느 요청이 막히고 어느 요청이 열려 있는지, 참여
// 정책 모듈의 우선순위)을 이미 고정하므로, 여기서 브라우저로 걷는 것은 화면이
// 그 판정을 실제로 다르게 보여주는지뿐이다 — 강사 화면에서 새 문제 만들기가
// 막힌 것으로 보이는지, 참여자 화면에서 제출 수단 대신 이유가 뜨는지
// 둘이다(시임 규약 ADR-0017/0021대로 준비 단계는 `request`로 API를 직접 친다).

test("보관된 클래스는 강사 화면에서 새 문제 만들기가 막힌 것으로 보인다", async ({ page }) => {
  const seed = `class-archive-instructor-${test.info().workerIndex}-${Date.now()}`;
  const className = `보관 확인용 클래스 ${Date.now()}`;

  await establishClassroomSession(page, seed);
  const api = classroomApi(page);

  const classResponse = await api.post("/api/backend/classroom/classes", {
    data: { name: className, instructor_display_name: "강사" },
  });
  expect(classResponse.ok()).toBeTruthy();
  const classId = (await classResponse.json()).id as number;

  await page.goto(`/classes/${classId}`);
  await expect(page.getByTestId("new-problem-link")).toBeVisible();

  await page.getByTestId("classroom-archive").click();
  await expect(page.getByTestId("classroom-archived-banner")).toBeVisible();

  // 보관되면 「새 문제」가 눌러도 아무 일도 하지 않는 자리로 바뀐다 — 링크가
  // 아예 사라지고 그 자리에 감춰진 이유가 남는다.
  await expect(page.getByTestId("new-problem-link")).toHaveCount(0);
  await expect(page.getByTestId("new-problem-blocked")).toBeVisible();

  // 직접 주소로 들어가도(우회) 폼 대신 이유가 뜬다 — 문은 여전히 백엔드다.
  await page.goto(`/classes/${classId}/problems/new`);
  await expect(page.getByTestId("new-problem-archived-note")).toContainText("보관되어 새 문제를 만들 수 없습니다");
});

test("보관된 클래스는 참여자의 제출이 이유와 함께 막힌다", async ({ page }) => {
  const seed = `class-archive-participant-${test.info().workerIndex}-${Date.now()}`;
  const className = `보관 제출 확인용 클래스 ${Date.now()}`;

  await establishClassroomSession(page, seed);
  const api = classroomApi(page);

  const classResponse = await api.post("/api/backend/classroom/classes", {
    data: { name: className, instructor_display_name: "강사" },
  });
  const classId = (await classResponse.json()).id as number;
  const joinCodeResponse = await api.get(`/api/backend/classroom/classes/${classId}`);
  const joinCode = (await joinCodeResponse.json()).join_code as string;

  const problemResponse = await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
    data: { title: "1주차", submission_formats: ["repository"] },
  });
  const problemId = (await problemResponse.json()).id as number;
  await api.post(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/checklist-items`,
    { data: { label: "통과 조건", required: true } },
  );
  await api.post(`/api/backend/classroom/classes/${classId}/problems/${problemId}/open`);

  // 참여자로 갈아타 가입해 둔다 — 보관 뒤에는 새 가입 자체가 막히므로 미리 한다.
  await page.context().clearCookies();
  const participantSeed = `${seed}-participant`;
  await establishClassroomSession(page, participantSeed);
  await api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "참여자" } });

  // 강사 세션으로 되돌아와 보관한다.
  await page.context().clearCookies();
  await establishClassroomSession(page, seed);
  await api.post(`/api/backend/classroom/classes/${classId}/archive`);

  // 참여자로 다시 갈아타 제출 화면을 연다 — 폼 대신 이유가 뜬다.
  await page.context().clearCookies();
  await establishClassroomSession(page, participantSeed);
  await page.goto(`/classes/${classId}/problems/${problemId}/submit`);

  await expect(page.getByTestId("class-archived-note")).toContainText("보관되어 새 제출을 받지 않습니다");
  await expect(page.getByTestId("repository-url-input")).toHaveCount(0);
});
