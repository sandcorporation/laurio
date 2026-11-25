import { expect, test, type Page } from "@playwright/test";

import {
  classroomApi,
  establishClassroomSession,
} from "./lib/cross-app-session";

// 강의실 — 클래스 상세의 강사 탭(시안 v2, #635). 소유권 이전·초대 링크 만들기·떠나기는 서버 상태를
// 바꾸므로 화면만 보고 끝내지 않고 끝까지 간다. 권한 표·만료·1회용은 백엔드 pytest 가 고정한다.
// 준비(클래스·초대 수락)는 세션을 바꿔 가며 API 를 직접 친다.

async function openClassWithCoInstructor(page: Page, seed: string) {
  await establishClassroomSession(page, seed);
  const api = classroomApi(page);
  const created = await api.post("/api/backend/classroom/classes", {
    data: { name: `강사 탭 ${seed}`, instructor_display_name: "김소유" },
  });
  const classId = (await created.json()).id as number;
  const invited = await api.post(
    `/api/backend/classroom/classes/${classId}/co-instructor-invites`,
  );
  const token = (await invited.json()).token as string;
  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-helper`);
  const accepted = await classroomApi(page).post(
    `/api/backend/classroom/co-instructor-invites/${token}/accept`,
    {
      data: { display_name: "박조교" },
    },
  );
  expect(accepted.ok()).toBeTruthy();
  return classId;
}

test("강사 탭 — 소유자가 초대 링크를 만들고 소유권을 넘기겠다 요청했다가 취소한다", async ({
  page,
}) => {
  const seed = `instructors-tab-owner-${test.info().workerIndex}-${Date.now()}`;
  const classId = await openClassWithCoInstructor(page, seed);
  await page.context().clearCookies();
  await establishClassroomSession(page, seed);

  await page.goto(`/classes/${classId}?tab=instructors`);
  await expect(page.getByTestId("class-instructors-count")).toHaveText("2명");
  await expect(page.getByTestId("class-leave")).toHaveCount(0);

  await page.getByTestId("co-instructor-invite-create").click();
  await expect(page.getByTestId("co-instructor-invite-row")).toHaveCount(1);

  // 줄마다 같은 이름이 되지 않게 대상 이름이 붙는다(#1436 4번).
  await expect(page.getByRole("button", { name: "박조교에게 소유권 넘기기" })).toBeVisible();
  await expect(page.getByRole("button", { name: "공동 강사 박조교 내보내기" })).toBeVisible();

  await page.getByTestId("ownership-transfer-start").click();
  await page.getByTestId("ownership-transfer-confirm-button").click();
  await expect(page.getByTestId("ownership-transfer-pending")).toBeVisible();
  // 보낸 뒤 초점이 BODY 로 떨어지지 않고 보낸 요청의 상태로 옮겨 가며, 읽힌다(#1435).
  await expect(page.getByTestId("ownership-transfer-pending")).toBeFocused();
  await expect(page.getByRole("status").filter({ hasText: "까지 답을 기다립니다" })).toBeVisible();
  await expect(page.getByTestId("ownership-transfer-start")).toHaveCount(0);
  // 대기 중인 줄에는 「요청 취소」만 — 내보내기가 없다(#669).
  await expect(page.getByTestId("co-instructor-remove")).toHaveCount(0);

  // 새로고침해도 대기 중이고, 취소하면 다시 넘길 수 있다.
  await page.reload();
  await expect(page.getByTestId("ownership-transfer-pending")).toBeVisible();
  await page.getByTestId("ownership-transfer-cancel").click();
  await expect(page.getByTestId("ownership-transfer-pending")).toHaveCount(0);
  await expect(page.getByTestId("ownership-transfer-start")).toBeVisible();
  await expect(page.getByTestId("co-instructor-remove")).toBeVisible();
});

test("강사 탭 — 공동 강사는 소유자 전용 행동 없이 떠나기만 보고, 떠나면 내 클래스 목록으로 간다", async ({
  page,
}) => {
  const seed = `instructors-tab-helper-${test.info().workerIndex}-${Date.now()}`;
  const classId = await openClassWithCoInstructor(page, seed);

  await page.goto(`/classes/${classId}?tab=instructors`);
  await expect(page.getByTestId("class-instructor-row")).toHaveCount(2);
  await expect(page.getByTestId("ownership-transfer-start")).toHaveCount(0);
  await expect(page.getByTestId("co-instructor-remove")).toHaveCount(0);

  await page.getByTestId("class-leave").click();
  await page.getByTestId("class-leave-confirm-button").click();
  await expect(page).toHaveURL("/");
  const gone = await classroomApi(page).get(
    `/api/backend/classroom/classes/${classId}`,
  );
  expect(gone.ok()).toBeFalsy();
});

test("강사 탭 — 공동 강사 초대는 「정말 취소」를 눌러야 취소된다", async ({
  page,
}) => {
  const seed = `instructors-tab-invite-${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, seed);
  const api = classroomApi(page);
  const created = await api.post("/api/backend/classroom/classes", {
    data: { name: `초대 취소 ${seed}`, instructor_display_name: "김소유" },
  });
  const classId = (await created.json()).id as number;
  const invitesPath = `/api/backend/classroom/classes/${classId}/co-instructor-invites`;
  await api.post(invitesPath);

  await page.goto(`/classes/${classId}?tab=instructors`);
  const confirm = page.getByTestId("co-instructor-invite-cancel-confirm-button");

  // 한 번 눌러서는 취소되지 않는다(#1378).
  await page.getByTestId("co-instructor-invite-cancel").click();
  await expect(confirm).toHaveText("정말 취소");
  expect(await (await api.get(invitesPath)).json()).toHaveLength(1);

  // 확인이 열리면 초점은 「그대로 두기」에 있고, 닫히면 「취소」로 돌아온다(#1400) — `body` 로 빠지지 않는다.
  const trigger = page.getByTestId("co-instructor-invite-cancel");
  const keep = page.getByTestId("co-instructor-invite-cancel-keep");
  await expect(keep).toBeFocused();
  await keep.click();
  await expect(confirm).toHaveCount(0);
  await expect(trigger).toBeFocused();

  // 키보드로 열고 Esc 로 닫는다.
  await page.keyboard.press("Enter");
  await expect(keep).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(confirm).toHaveCount(0);
  await expect(trigger).toBeFocused();

  await trigger.click();
  await confirm.click();
  await expect(page.getByTestId("co-instructor-invite-row")).toHaveCount(0);
  await expect(page.getByTestId("co-instructor-invite-create")).toBeFocused();
});

test("소유권 이전 — 받는 공동 강사가 넘겨받으면 결과 문구가 읽히고 초점을 받으며, 받은 알림은 끝난 요청이라고 말한다", async ({
  page,
}) => {
  const seed = `transfer-accept-${test.info().workerIndex}-${Date.now()}`;
  const classId = await openClassWithCoInstructor(page, seed);
  // 소유자가 이전을 요청한다.
  await page.context().clearCookies();
  await establishClassroomSession(page, seed);
  const ownerApi = classroomApi(page);
  const roster = (await (await ownerApi.get(`/api/backend/classroom/classes/${classId}/instructors`)).json()) as {
    co_instructor_id: number | null;
  }[];
  const coId = roster.find((row) => row.co_instructor_id !== null)!.co_instructor_id;
  const requested = await ownerApi.post(`/api/backend/classroom/classes/${classId}/ownership-transfers`, {
    data: { co_instructor_id: coId },
  });
  expect(requested.ok()).toBeTruthy();

  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-helper`);
  await page.goto(`/classes/${classId}`);
  // 요청 카드는 이름 있는 영역이다.
  await expect(page.getByRole("region", { name: "소유권 이전 요청" })).toBeVisible();

  await page.getByTestId("ownership-transfer-accept").click();
  const note = page.getByRole("status").filter({ has: page.getByTestId("ownership-transfer-accepted-note") });
  await expect(note).toBeVisible();
  await expect(note).toBeFocused();

  // 받은 알림의 문구는 받은 때의 것 — 끝난 요청이면 수락·거절을 청하지 않는다(#1436 5번).
  await page.goto("/notifications");
  await expect(page.getByText("소유권 이전 요청을 수락했습니다 — 이제 내가 이 클래스의 소유자입니다.")).toBeVisible();
  await expect(page.getByText("수락하거나 거절해 주세요")).toHaveCount(0);
});

test("소유권 이전 — 받는 공동 강사가 거절해도 결과 문구가 읽히고 초점을 받는다", async ({ page }) => {
  const seed = `transfer-decline-${test.info().workerIndex}-${Date.now()}`;
  const classId = await openClassWithCoInstructor(page, seed);
  await page.context().clearCookies();
  await establishClassroomSession(page, seed);
  const ownerApi = classroomApi(page);
  const roster = (await (await ownerApi.get(`/api/backend/classroom/classes/${classId}/instructors`)).json()) as {
    co_instructor_id: number | null;
  }[];
  const coId = roster.find((row) => row.co_instructor_id !== null)!.co_instructor_id;
  await ownerApi.post(`/api/backend/classroom/classes/${classId}/ownership-transfers`, {
    data: { co_instructor_id: coId },
  });

  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-helper`);
  await page.goto(`/classes/${classId}`);
  await page.getByTestId("ownership-transfer-decline").click();
  const note = page.getByRole("status").filter({ has: page.getByTestId("ownership-transfer-declined-note") });
  await expect(note).toBeFocused();
});

async function ownerWithPendingRequest(page: Page, seed: string) {
  const classId = await openClassWithCoInstructor(page, seed);
  await page.context().clearCookies();
  await establishClassroomSession(page, seed);
  const ownerApi = classroomApi(page);
  const roster = (await (await ownerApi.get(`/api/backend/classroom/classes/${classId}/instructors`)).json()) as {
    co_instructor_id: number | null;
  }[];
  const coId = roster.find((row) => row.co_instructor_id !== null)!.co_instructor_id;
  const requested = await ownerApi.post(`/api/backend/classroom/classes/${classId}/ownership-transfers`, {
    data: { co_instructor_id: coId },
  });
  return { classId, transferId: (await requested.json()).id as number };
}

async function helperAccepts(page: Page, seed: string, classId: number, transferId: number) {
  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-helper`);
  const accepted = await classroomApi(page).post(
    `/api/backend/classroom/classes/${classId}/ownership-transfers/${transferId}/accept`,
  );
  expect(accepted.ok()).toBeTruthy();
  await page.context().clearCookies();
  await establishClassroomSession(page, seed);
}

test("소유권 이전 — 받는 사람이 넘겨받으면 열려 있는 소유자 화면이 저절로 맞춰지고 그 사실이 읽힌다 (#1441 5번)", async ({
  page,
  browser,
}) => {
  test.setTimeout(20_000);
  const seed = `transfer-live-${test.info().workerIndex}-${Date.now()}`;
  const { classId, transferId } = await ownerWithPendingRequest(page, seed);
  await page.goto(`/classes/${classId}?tab=instructors`);
  await expect(page.getByTestId("ownership-transfer-cancel")).toBeVisible();

  // 받는 사람은 다른 브라우저에서 넘겨받는다 — 열려 있는 소유자 화면의 쿠키는 그대로다.
  const helperContext = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const helperPage = await helperContext.newPage();
  await establishClassroomSession(helperPage, `${seed}-helper`);
  const accepted = await classroomApi(helperPage).post(
    `/api/backend/classroom/classes/${classId}/ownership-transfers/${transferId}/accept`,
  );
  expect(accepted.ok()).toBeTruthy();
  await helperContext.close();

  const note = page.getByRole("status").filter({ has: page.getByTestId("ownership-transfer-taken-note") });
  await expect(note).toContainText("박조교님이 소유권을 넘겨받았습니다");
  await expect(note).toBeFocused();
  await expect(page.getByTestId("ownership-transfer-pending")).toHaveCount(0);
});

test("소유권 이전 — 넘어간 뒤 소유자가 「요청 취소」를 누르면 「이미 넘겨받았습니다」가 읽히고 초점을 받는다 (#1441 5번)", async ({
  page,
}) => {
  const seed = `transfer-taken-${test.info().workerIndex}-${Date.now()}`;
  const { classId, transferId } = await ownerWithPendingRequest(page, seed);
  // 실시간 신호가 닿지 않는 화면 — 눌러서야 사실을 알게 되는 길.
  await page.route("**/classroom/events/stream", (route) => route.abort());
  await page.goto(`/classes/${classId}?tab=instructors`);
  await expect(page.getByTestId("ownership-transfer-cancel")).toBeVisible();

  await helperAccepts(page, seed, classId, transferId);

  await page.getByTestId("ownership-transfer-cancel").click();
  const note = page.getByRole("status").filter({ has: page.getByTestId("ownership-transfer-taken-note") });
  await expect(note).toContainText("이미 박조교님이 넘겨받았습니다");
  await expect(note).toBeFocused();
  await expect(page.getByTestId("ownership-transfer-pending")).toHaveCount(0);
});
