import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 템플릿 공개·내리기·신고, 클래스 이름 저장 실패의 접근성(#1446, #1447 1-3·2-1·11).
// 렌더된 컨트롤의 초점·접근성 이름·상태 영역을 본다 — 구현 줄을 지우면 붉어져야 한다.

const API = "/api/backend/classroom";

// 두 세션을 오가는 시험이 있어 기본 3초는 콜드 스타트에 빠듯하다.
test.describe.configure({ timeout: 15_000 });

async function newClass(page: import("@playwright/test").Page, name: string) {
  const created = await classroomApi(page).post(`${API}/classes`, {
    data: { name, instructor_display_name: "김소유" },
  });
  expect(created.ok()).toBeTruthy();
  return (await created.json()).id as number;
}

test("클래스 템플릿을 공개하면 공유 링크로, 내리면 이름 칸으로 초점이 가고 결과가 읽힌다", async ({ page }) => {
  const stamp = `${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, `e2e-tpl-focus-${stamp}`);
  const classId = await newClass(page, `공개 초점 ${stamp}`);
  await page.goto(`/classes/${classId}/settings#class-template`);

  await page.getByLabel("공개할 때 보일 이름").fill("김강사");
  await page.getByRole("button", { name: "클래스를 템플릿으로 공개" }).click();
  await expect(page.getByTestId("publish-class-template-share-link")).toBeFocused();
  await expect(page.getByTestId("publish-class-template-result")).toHaveText("템플릿으로 공개했습니다.");
  await expect(page.getByTestId("publish-class-template-result")).toHaveAttribute("role", "status");

  await page.getByRole("button", { name: "내리기" }).click();
  await expect(page.getByLabel("공개할 때 보일 이름")).toBeFocused();
  await expect(page.getByTestId("publish-class-template-result")).toHaveText("템플릿을 내렸습니다.");
});

test("공개자가 아닌 강사에게는 내리기 단추가 없고 공개한 사람만 보인다", async ({ page: coPage, browser }) => {
  let page = coPage;
  const stamp = `${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, `e2e-tpl-owner-${stamp}`);
  const classId = await newClass(page, `공개자 구분 ${stamp}`);
  const invite = await classroomApi(page).post(`${API}/classes/${classId}/co-instructor-invites`);
  const token = (await invite.json()).token as string;

  await page.context().clearCookies();
  await establishClassroomSession(page, `e2e-tpl-co-${stamp}`);
  const accepted = await classroomApi(page).post(`${API}/co-instructor-invites/${token}/accept`, {
    data: { display_name: "박공동" },
  });
  expect(accepted.ok()).toBeTruthy();
  const published = await classroomApi(page).post(`${API}/classes/${classId}/publish-template`, {
    data: { publisher_display_name: "박공동" },
  });
  expect(published.ok()).toBeTruthy();

  // 공개한 사람 — 내리기가 있다.
  await page.goto(`/classes/${classId}/settings#class-template`);
  await expect(page.getByRole("button", { name: "내리기" })).toBeVisible();

  // 소유자 — 공개자가 아니므로 단추 대신 공개한 사람. 세션이 다른 사람이라 새 컨텍스트로 연다.
  const ownerContext = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const ownerPage = await ownerContext.newPage();
  await establishClassroomSession(ownerPage, `e2e-tpl-owner-${stamp}`);
  page = ownerPage;
  await page.goto(`/classes/${classId}/settings#class-template`);
  await expect(page.getByTestId("publish-class-template-done")).toBeVisible();
  await expect(page.getByRole("button", { name: "내리기" })).toHaveCount(0);
  await expect(page.getByText("공개: 박공동")).toBeVisible();
});

test("템플릿 신고를 접수하면 접수 안내로 초점이 가고 상태로 읽힌다", async ({ page }) => {
  const stamp = `${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, `e2e-tpl-pub-${stamp}`);
  const classId = await newClass(page, `신고 원본 ${stamp}`);
  const problem = await classroomApi(page).post(`${API}/classes/${classId}/problems`, {
    data: { title: `신고 대상 ${stamp}`, description: "설명", submission_formats: ["source"] },
  });
  const problemId = (await problem.json()).id as number;
  const published = await classroomApi(page).post(`${API}/classes/${classId}/problems/${problemId}/publish-template`, {
    data: { publisher_display_name: "공개자" },
  });
  const shareCode = (await published.json()).share_code as string;

  await page.context().clearCookies();
  await establishClassroomSession(page, `e2e-tpl-reporter-${stamp}`);
  await page.goto(`/templates/${shareCode}`);
  await page.getByRole("button", { name: "부적절한 템플릿 신고" }).click();
  await page.getByLabel("신고 사유").fill("부적절합니다");
  await page.getByRole("button", { name: "신고하기" }).click();

  const done = page.getByRole("status").filter({ hasText: "신고가 접수되었습니다" });
  await expect(done).toBeVisible();
  await expect(done).toBeFocused();
});

test("이름 저장이 접근 상실로 실패하면 안내 곁에 저장되지 않은 값이 남는다", async ({ page }) => {
  const stamp = `${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, `e2e-tpl-draft-${stamp}`);
  const classId = await newClass(page, `초안 유지 ${stamp}`);
  await page.goto(`/classes/${classId}/settings`);
  await page.getByLabel("클래스 이름").fill("새 이름 초안");

  // 소유자가 내보낸 것과 같다 — 저장은 404 로 실패하고, 이어 읽기도 404 다.
  const url = `**/api/backend/classroom/classes/${classId}`;
  let revoked = false;
  await page.route(url, async (route) => {
    const method = route.request().method();
    if (method === "PATCH") {
      revoked = true;
      return route.fulfill({ status: 404, json: { detail: "클래스를 찾을 수 없습니다." } });
    }
    if (method === "GET" && revoked) {
      return route.fulfill({ status: 404, json: { detail: "클래스를 찾을 수 없습니다." } });
    }
    return route.continue();
  });
  await page.getByTestId("class-instructor-display-name-submit").click();

  await expect(page.getByTestId("class-settings-not-found")).toBeFocused();
  await expect(page.getByLabel("클래스 이름")).toHaveValue("새 이름 초안");
  await expect(page.getByTestId("class-unsaved-error")).toHaveText("클래스를 찾을 수 없습니다.");
  await expect(page.getByRole("button", { name: "복사" })).toBeVisible();
});

test("신고 칸을 열면 사유 칸으로, 취소하면 신고 단추로 초점이 돌아온다", async ({ page }) => {
  const stamp = `${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, `e2e-rpt-pub-${stamp}`);
  const classId = await newClass(page, `신고 초점 ${stamp}`);
  const problem = await classroomApi(page).post(`${API}/classes/${classId}/problems`, {
    data: { title: `신고 초점 ${stamp}`, description: "설명", submission_formats: ["source"] },
  });
  const problemId = (await problem.json()).id as number;
  const published = await classroomApi(page).post(`${API}/classes/${classId}/problems/${problemId}/publish-template`, {
    data: { publisher_display_name: "공개자" },
  });
  const shareCode = (await published.json()).share_code as string;
  await page.context().clearCookies();
  await establishClassroomSession(page, `e2e-rpt-viewer-${stamp}`);

  await page.goto(`/templates/${shareCode}`);
  await page.getByRole("button", { name: "부적절한 템플릿 신고" }).click();
  await expect(page.getByLabel("신고 사유")).toBeFocused();
  await page.getByRole("button", { name: "취소" }).click();
  await expect(page.getByRole("button", { name: "부적절한 템플릿 신고" })).toBeFocused();
});

test("클래스·강사 이름을 저장하면 「저장했습니다」가 상태로 읽히고, 다시 고치면 사라진다", async ({ page }) => {
  const stamp = `${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, `e2e-name-saved-${stamp}`);
  const classId = await newClass(page, `이름 저장 ${stamp}`);
  await page.goto(`/classes/${classId}/settings`);

  await page.getByLabel("클래스 이름").fill(`새 이름 ${stamp}`);
  await page.getByTestId("class-instructor-display-name-submit").click();
  await expect(page.getByRole("status").filter({ hasText: "저장했습니다." })).toBeVisible();

  await page.getByLabel("클래스 이름").fill(`또 고침 ${stamp}`);
  await expect(page.getByRole("status").filter({ hasText: "저장했습니다." })).toHaveCount(0);
});
