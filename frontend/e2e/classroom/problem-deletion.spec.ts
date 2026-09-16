import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 아무도 내지 않은 문제를 강사가 지운다 (#430).
//
// 클래스 삭제(class-deletion.spec.ts)와 같은 역할 분담이다: 백엔드 pytest가
// 판정 로직(시도 유무·소유권·cascade·템플릿 독립성)을 이미 고정하므로, 여기서
// 브라우저로 걷는 것은 화면의 확인 절차(제목을 다시 쳐야 눌린다)와 두 상태
// (가능/불가능)가 실제로 다르게 보이는지뿐이다 — 준비 단계는 `request`로
// API를 직접 친다(ADR-0017/0021).

test("시도가 없는 문제는 제목을 다시 쳐야 지워지고, 지우면 목록에서 사라진다", async ({
  page,
}) => {
  const seed = `problem-deletion-${test.info().workerIndex}-${Date.now()}`;
  const className = `문제 삭제 테스트 클래스 ${Date.now()}`;
  const problemTitle = `지울 문제 ${Date.now()}`;

  await establishClassroomSession(page, seed);
  const api = classroomApi(page);

  const classResponse = await api.post("/api/backend/classroom/classes", {
    data: { name: className, instructor_display_name: "강사" },
  });
  expect(classResponse.ok()).toBeTruthy();
  const classId = (await classResponse.json()).id as number;

  const problemResponse = await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
    data: { title: problemTitle, submission_formats: ["repository"] },
  });
  expect(problemResponse.ok()).toBeTruthy();
  const problemId = (await problemResponse.json()).id as number;
  await api.post(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/checklist-items`,
    { data: { label: "통과 조건", required: true } },
  );

  await page.goto(`/classes/${classId}/problems/${problemId}`);
  await page.getByTestId("delete-problem-open").click();

  // 지워질 것(체크리스트 1개)을 먼저 보여준다.
  await expect(page.getByTestId("delete-problem-warning")).toContainText("체크리스트 항목 1개");

  // 잘못된 제목으로는 눌리지 않는다 — 실수로 지워지지 않는다는 AC.
  await page.getByTestId("delete-problem-confirm-input").fill("아무 제목");
  await expect(page.getByTestId("delete-problem-confirm")).toBeDisabled();

  await page.getByTestId("delete-problem-confirm-input").fill(problemTitle);
  await expect(page.getByTestId("delete-problem-confirm")).toBeEnabled();
  await page.getByTestId("delete-problem-confirm").click();

  await expect(page).toHaveURL(`/classes/${classId}`);
  await expect(page.getByTestId(`problem-row-${problemId}`)).toHaveCount(0);
});

test("시도가 있는 문제는 삭제 버튼 대신 숨기기 안내가 뜬다", async ({ page }) => {
  const seed = `problem-deletion-blocked-${test.info().workerIndex}-${Date.now()}`;
  const className = `제출있음 문제 테스트 클래스 ${Date.now()}`;

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

  // 참여자로 잠깐 갈아타 시도 하나를 남긴다.
  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-participant`);
  await api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "참여자" } });
  await api.post(`/api/backend/classroom/classes/${classId}/problems/${problemId}/submissions`, {
    data: { value: "https://github.com/octocat/hello", submission_format: "repository" },
  });

  // 강사 세션으로 되돌아와 삭제 카드가 거절 안내로 바뀌어 있는지 본다.
  await page.context().clearCookies();
  await establishClassroomSession(page, seed);
  await page.goto(`/classes/${classId}/problems/${problemId}`);

  await expect(page.getByTestId("delete-problem-blocked")).toContainText("지울 수 없습니다");
  await expect(page.getByTestId("delete-problem-open")).toHaveCount(0);
});
