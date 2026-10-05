import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 공동 강사 초대를 받은 사람이 로그아웃 상태로 링크를 열고, 로그인한 뒤 같은
// 초대로 돌아와 강사 이름을 넣고 수락하면 그 클래스의 강사 화면에 이른다 (#561).
//
// 1회용·만료·이미 강사·권한 표는 백엔드 pytest 가 고정한다(`test_classroom_co_instructor_*`).
// 여기서 걷는 것은 화면의 흐름 하나 — 인증 구역 밖의 초대 화면, 로그인 왕복이 같은 초대로
// 돌아오는 것, 수락 뒤 강사 화면이다. 준비(클래스·초대)는 소유자 세션으로 API 를 직접 친다.
//
// 공개 앱의 실제 로그인은 dev 에서 부모 도메인 쿠키를 재현할 수 없어 걷지 않는다
// (`lib/cross-app-session.ts`) — 강의실 `/login` 이 공개 앱에 `next=/invite/<토큰>` 을
// 싣는지 본 뒤, 세션을 심고 그 주소로 간다(공개 앱이 로그인 뒤 하는 일과 같다).

test("로그아웃 상태로 초대 링크를 열고 로그인하면 같은 초대로 돌아와 수락하고 강사 화면에 이른다", async ({
  page,
}) => {
  const stamp = `${test.info().workerIndex}-${Date.now()}`;
  const className = `공동 강사 초대 ${stamp}`;

  // 소유자 세션으로 클래스와 초대를 만든 뒤 쿠키를 지워 로그아웃 상태로 돌아간다 — 컨텍스트를
  // 하나 더 열지 않는다(시험 하나 3초).
  await establishClassroomSession(page, `e2e-co-owner-${stamp}`);
  const api = classroomApi(page);
  const created = await api.post("/api/backend/classroom/classes", {
    data: { name: className, instructor_display_name: "김소유" },
  });
  expect(created.ok()).toBeTruthy();
  const classId = (await created.json()).id as number;
  const invited = await api.post(`/api/backend/classroom/classes/${classId}/co-instructor-invites`);
  expect(invited.ok()).toBeTruthy();
  const token = (await invited.json()).token as string;
  await page.context().clearCookies();

  // 로그인하지 않은 사람 — 미들웨어가 막지 않고 무엇을 수락하는지 먼저 보여 준다.
  await page.goto(`/invite/${token}`);
  await expect(page.getByTestId("invite-class-name")).toHaveText(className);
  await expect(page.getByTestId("invite-instructors")).toContainText("김소유");
  await page.getByTestId("invite-login-link").click();

  // 강의실 `/login` 이 공개 앱으로 보내며 돌아올 자리를 싣는다.
  await expect(page).toHaveURL(/\/login\?next=/);
  const href = await page.getByTestId("classroom-login-link").getAttribute("href");
  const returnPath = new URL(href ?? "").searchParams.get("next");
  expect(returnPath).toBe(`/invite/${token}`);

  // 공개 앱 로그인이 끝난 것과 같다 — 세션을 심고 돌아올 자리로 간다.
  await establishClassroomSession(page, `e2e-co-helper-${stamp}`);
  await page.goto(returnPath ?? "/");
  await page.getByTestId("invite-display-name-input").fill("박보조");
  await page.getByTestId("invite-accept").click();

  await expect(page).toHaveURL(`/classes/${classId}`);
  await expect(page.getByTestId("classroom-detail-co-instructor-badge")).toBeVisible();
});
