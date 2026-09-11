import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 제출이 없는 클래스를 강사가 지운다 (#330).
//
// 이 플랫폼의 첫 진짜 삭제(하드 딜리트)다 — 되돌릴 수 없고, 잘못 누르면 문제·
// 체크리스트·참여자 가입이 통째로 사라진다. 백엔드 pytest가 판정 로직(제출
// 유무·소유권·cascade·템플릿 독립성)을 이미 고정하므로, 여기서 브라우저로
// 걷는 것은 화면의 확인 절차(이름을 다시 쳐야 눌린다)와 두 상태(가능/불가능)가
// 실제로 다르게 보이는지뿐이다 — 시임 규약(ADR-0017/0021)대로 준비 단계는
// `request`로 API를 직접 친다.

test("제출이 없는 클래스는 이름을 다시 쳐야 지워지고, 지우면 목록에서 사라진다", async ({
  page,
}) => {
  const seed = `class-deletion-${test.info().workerIndex}-${Date.now()}`;
  const className = `삭제 테스트 클래스 ${Date.now()}`;

  await establishClassroomSession(page, seed);
  const api = classroomApi(page);

  const classResponse = await api.post("/api/backend/classroom/classes", {
    data: { name: className, instructor_display_name: "강사" },
  });
  expect(classResponse.ok()).toBeTruthy();
  const classId = (await classResponse.json()).id as number;

  const problemResponse = await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
    data: { title: "1주차", submission_format: "repository" },
  });
  expect(problemResponse.ok()).toBeTruthy();
  const problemId = (await problemResponse.json()).id as number;
  await api.post(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/checklist-items`,
    { data: { label: "통과 조건", required: true } },
  );

  await page.goto(`/classes/${classId}/settings`);
  await page.getByTestId("delete-class-open").click();

  // 지워질 것(문제 1개·체크리스트 1개·참여자 0명)을 먼저 보여준다.
  await expect(page.getByTestId("delete-class-warning")).toContainText("문제 1개");
  await expect(page.getByTestId("delete-class-warning")).toContainText("체크리스트 항목 1개");

  // 잘못된 이름으로는 눌리지 않는다 — 실수로 지워지지 않는다는 AC.
  await page.getByTestId("delete-class-confirm-input").fill("아무 이름");
  await expect(page.getByTestId("delete-class-confirm")).toBeDisabled();

  await page.getByTestId("delete-class-confirm-input").fill(className);
  await expect(page.getByTestId("delete-class-confirm")).toBeEnabled();
  await page.getByTestId("delete-class-confirm").click();

  await expect(page).toHaveURL("/");
  await expect(page.getByTestId(`classroom-row-${classId}`)).toHaveCount(0);
});

test("제출이 있는 클래스는 삭제 버튼 대신 보관 안내가 뜬다", async ({ page }) => {
  const seed = `class-deletion-blocked-${test.info().workerIndex}-${Date.now()}`;
  const className = `제출있음 테스트 클래스 ${Date.now()}`;

  await establishClassroomSession(page, seed);
  const api = classroomApi(page);

  const classResponse = await api.post("/api/backend/classroom/classes", {
    data: { name: className, instructor_display_name: "강사" },
  });
  const classId = (await classResponse.json()).id as number;
  const joinCodeResponse = await api.get(`/api/backend/classroom/classes/${classId}`);
  const joinCode = (await joinCodeResponse.json()).join_code as string;

  const problemResponse = await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
    data: { title: "1주차", submission_format: "repository" },
  });
  const problemId = (await problemResponse.json()).id as number;
  await api.post(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/checklist-items`,
    { data: { label: "통과 조건", required: true } },
  );
  await api.post(`/api/backend/classroom/classes/${classId}/problems/${problemId}/open`);

  // 참여자로 잠깐 갈아타 제출 하나를 남긴다.
  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-participant`);
  await api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "참여자" } });
  await api.post(`/api/backend/classroom/classes/${classId}/problems/${problemId}/submissions`, {
    data: { value: "https://github.com/octocat/hello" },
  });

  // 강사 세션으로 되돌아와 삭제 카드가 거절 안내로 바뀌어 있는지 본다.
  await page.context().clearCookies();
  await establishClassroomSession(page, seed);
  await page.goto(`/classes/${classId}/settings`);

  await expect(page.getByTestId("delete-class-blocked")).toContainText("지울 수 없습니다");
  await expect(page.getByTestId("delete-class-open")).toHaveCount(0);
});
