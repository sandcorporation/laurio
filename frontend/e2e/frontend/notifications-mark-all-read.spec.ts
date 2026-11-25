import { expect, test } from "@playwright/test";

import { establishDeveloperSession } from "../lib/session";

// 공개 앱 알림 목록의 「모두 읽음」(#1476) — 강의실과 같은 규약: 초점은 제목으로, 결과는 늘 있는 status 영역이 읽는다.
// 안 읽은 알림은 서버 응답을 바꿔 만든다(공개 앱 알림은 운영팀이 보내는 것이라 공개 API 로 만들 수 없다).

test("「모두 읽음」을 Enter 로 누르면 초점이 알림 제목으로 가고 status 가 결과를 읽는다", async ({ page }) => {
  await establishDeveloperSession(page, `mark-all-public-${test.info().workerIndex}-${Date.now()}`, null);

  let unread = 1;
  await page.route("**/api/backend/notifications/unread-count", (route) =>
    route.fulfill({ json: { count: unread } }),
  );
  await page.route("**/api/backend/notifications/mark-read", (route) => {
    unread = 0;
    return route.fulfill({ json: { marked: 1 } });
  });
  await page.route("**/api/backend/notifications/me*", (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: 9001,
            notification_type: "operator_notice",
            status: "sent",
            title: "공지",
            body: "본문",
            read_at: null,
            created_at: new Date().toISOString(),
            has_image: false,
            context: {},
            dispatches: [],
          },
        ],
        count: 1,
        next: null,
      },
    }),
  );

  await page.goto("/console/notifications");
  const status = page.getByTestId("notifications-status");
  await expect(status).toHaveAttribute("role", "status");
  await expect(status).toHaveText("");

  const markAll = page.getByTestId("notifications-mark-all-read");
  await markAll.focus();
  await page.keyboard.press("Enter");

  await expect(markAll).toHaveCount(0);
  await expect(page.getByTestId("notifications-heading")).toBeFocused();
  await expect(status).toHaveText("알림을 모두 읽음으로 표시했습니다");
});
