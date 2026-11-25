import { expect, test, type Page } from "@playwright/test";

import {
  classroomApi,
  establishClassroomSession,
} from "./lib/cross-app-session";

// 받는 사람이 클래스를 떠나 소유권 이전 요청이 지워졌다(#1448 일부-6·②) — 받은 알림은 「끝난 요청」이라고 말하고
// 수락·거절을 청하지 않는다. 알림 줄은 링크라 키보드 초점·낭독기 이름·390px 터치가 같은 문구에 닿는다.

const GONE = "소유권 이전 요청은 이미 끝났습니다 — 더 답할 것이 없습니다.";

// 요청에 잇지 못한 옛 알림인데 그 클래스에 대기 요청이 있다(#1459 ①) — 끝났다고 단정하지 않고 요청 카드로 보낸다.
// 옛 알림(`transfer_id` 없음)은 공개 API 로 만들 수 없어 목록 응답의 상태만 서버가 내는 값으로 바꾼다 — 그 값을
// 언제 내는지는 백엔드 시험(`test_classroom_legacy_transfer_notifications.py`)이 본다.
const UNKNOWN =
  "클래스에 나에게 온 소유권 이전 요청이 지금 대기 중입니다 — 이 알림이 그 요청인지는 알 수 없으니 클래스 화면의 요청 카드에서 확인하고 답해 주세요.";

async function unlinkedRequestNotification(page: Page) {
  await page.route("**/api/backend/notifications/me?classroom_only=true*", async (route) => {
    const response = await route.fetch();
    const body = (await response.json()) as { items: { notification_type: string; transfer_status?: string | null }[] };
    for (const item of body.items) {
      if (item.notification_type === "classroom_ownership_transfer_requested") item.transfer_status = "unknown";
    }
    await route.fulfill({ response, json: body });
  });
}

async function recipientWithPendingRequest(page: Page, seed: string) {
  await recipientOfRequest(page, seed, { removeAfterRequest: false });
}

async function recipientWhoseRequestWasRemoved(page: Page, seed: string) {
  await recipientOfRequest(page, seed, { removeAfterRequest: true });
}

async function recipientOfRequest(page: Page, seed: string, { removeAfterRequest }: { removeAfterRequest: boolean }) {
  await establishClassroomSession(page, seed);
  const ownerApi = classroomApi(page);
  const created = await ownerApi.post("/api/backend/classroom/classes", {
    data: { name: `이전 알림 ${seed}`, instructor_display_name: "김소유" },
  });
  const classId = (await created.json()).id as number;
  const invited = await ownerApi.post(`/api/backend/classroom/classes/${classId}/co-instructor-invites`);
  const token = (await invited.json()).token as string;

  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-helper`);
  const accepted = await classroomApi(page).post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, {
    data: { display_name: "박조교" },
  });
  expect(accepted.ok()).toBeTruthy();

  // 소유자가 이전을 요청한다 — 내보내면 대기 요청은 행째 지워진다.
  await page.context().clearCookies();
  await establishClassroomSession(page, seed);
  const owner = classroomApi(page);
  const roster = (await (await owner.get(`/api/backend/classroom/classes/${classId}/instructors`)).json()) as {
    co_instructor_id: number | null;
  }[];
  const coId = roster.find((row) => row.co_instructor_id !== null)!.co_instructor_id;
  const requested = await owner.post(`/api/backend/classroom/classes/${classId}/ownership-transfers`, {
    data: { co_instructor_id: coId },
  });
  expect(requested.ok()).toBeTruthy();
  if (removeAfterRequest) {
    const removed = await owner.post(`/api/backend/classroom/classes/${classId}/co-instructors/${coId}/remove`);
    expect(removed.status()).toBe(204);
  }

  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-helper`);
}

test("지워진 요청의 알림은 끝난 요청이라고 말한다 — 키보드 초점과 낭독기 이름", async ({ page }) => {
  await recipientWhoseRequestWasRemoved(page, `transfer-gone-${test.info().workerIndex}-${Date.now()}`);

  await page.goto("/notifications");
  const row = page.getByRole("link", { name: new RegExp(GONE) });
  await expect(row).toBeVisible();
  await expect(page.getByText("수락하거나 거절해 주세요")).toHaveCount(0);

  await row.focus();
  await expect(row).toBeFocused();
});

test("어느 요청인지 모르는 옛 알림은 끝났다고 하지 않고 요청 카드로 보낸다 — 키보드·낭독기 이름 (#1459 ①)", async ({
  page,
}) => {
  await recipientWithPendingRequest(page, `transfer-unknown-${test.info().workerIndex}-${Date.now()}`);
  await unlinkedRequestNotification(page);

  await page.goto("/notifications");
  const row = page.getByRole("link", { name: new RegExp(UNKNOWN) });
  await expect(row).toBeVisible();
  await expect(page.getByText(GONE)).toHaveCount(0);

  await row.focus();
  await expect(row).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("region", { name: "소유권 이전 요청" })).toBeVisible();
});

test.describe("390px 터치", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("지워진 요청의 알림은 좁은 화면에서도 끝난 요청이라고 말하고 눌린다", async ({ page }) => {
    await recipientWhoseRequestWasRemoved(page, `transfer-gone-touch-${test.info().workerIndex}-${Date.now()}`);

    await page.goto("/notifications");
    const row = page.getByRole("link", { name: new RegExp(GONE) });
    await expect(row).toBeInViewport();
    await expect(page.getByText("수락하거나 거절해 주세요")).toHaveCount(0);
    const href = await row.getAttribute("href");
    await row.tap();
    await expect(page).toHaveURL(new RegExp(`${href!.split("?")[0]}`));
  });

  test("어느 요청인지 모르는 옛 알림은 좁은 화면에서도 눌려 요청 카드로 간다 (#1459 ①)", async ({ page }) => {
    await recipientWithPendingRequest(page, `transfer-unknown-touch-${test.info().workerIndex}-${Date.now()}`);
    await unlinkedRequestNotification(page);

    await page.goto("/notifications");
    const row = page.getByRole("link", { name: new RegExp(UNKNOWN) });
    await expect(row).toBeInViewport();
    await row.tap();
    await expect(page.getByRole("region", { name: "소유권 이전 요청" })).toBeVisible();
  });
});
