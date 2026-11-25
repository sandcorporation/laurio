import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 「만들고 바로 열기」가 필수 항목이 없어 꺼졌을 때의 이유는 단추 옆 보이는 글이다(#1441-1) —
// 터치·키보드·화면 낭독기에도 닿도록 `aria-describedby` 로 묶는다.

test("필수 항목이 없으면 꺼진 단추 옆에 이유가 보이고 단추가 그 글을 가리킨다(390px)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await establishClassroomSession(page, `open-blocked-${test.info().workerIndex}-${Date.now()}`);
  const api = classroomApi(page);
  const created = await api.post("/api/backend/classroom/classes", {
    data: { name: `열기 막힘 ${Date.now()}`, instructor_display_name: "강사" },
  });
  const classId = (await created.json()).id as number;

  await page.goto(`/classes/${classId}/problems/new`);
  await page.getByTestId("new-problem-title-input").fill("필수 없는 문제");

  const open = page.getByTestId("new-problem-create-and-open-submit");
  const reason = page.getByTestId("new-problem-open-blocked-reason");
  await expect(open).toBeDisabled();
  await expect(reason).toBeVisible();
  await expect(reason).toHaveText("필수 항목이 없어 아직 열 수 없습니다.");
  await expect(open).toHaveAttribute("aria-describedby", (await reason.getAttribute("id")) ?? "");
  await expect(open).not.toHaveAttribute("title", /.+/);
});
