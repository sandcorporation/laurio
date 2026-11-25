import { expect, test } from "@playwright/test";

import { establishClassroomSession } from "./lib/cross-app-session";

// 12차 사용 리뷰 #1492-4 — 「읽음」 단추는 링크가 없는 안 읽은 알림 줄에만 뜨고, 줄마다 같은 글자라 어느 알림 것인지가 이름에 있다.
// 실제 알림은 모두 class_id 가 있어 링크가 생기므로, 목록 응답만 가로채 class_id 없는 알림 둘을 넣는다(렌더는 실제 화면).
test("링크 없는 안 읽은 알림 줄의 「읽음」 단추는 어느 알림 것인지를 이름에 담는다", async ({ page }) => {
  await establishClassroomSession(page, `mark-read-name-${test.info().workerIndex}-${Date.now()}`);
  const row = (id: number, className: string) => ({
    id,
    notification_type: "classroom_member_expelled",
    is_transactional: true,
    is_promotional: false,
    status: "sent",
    scheduled_for: null,
    created_at: "2026-11-25T01:00:00Z",
    context: { class_name: className },
    dispatches: [],
    read_at: null,
  });
  await page.route("**/api/backend/notifications/me**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [row(9001, "가나 클래스"), row(9002, "다라 클래스")], count: 2, next: null }),
    });
  });
  await page.goto("/notifications");
  const first = page.getByRole("button", { name: /^읽음 '가나 클래스' 클래스에서 내보내졌습니다/ });
  const second = page.getByRole("button", { name: /^읽음 '다라 클래스' 클래스에서 내보내졌습니다/ });
  await expect(first).toHaveText("읽음");
  await expect(second).toHaveText("읽음");
  await expect(page.getByRole("button", { name: "읽음", exact: true })).toHaveCount(0);
});
