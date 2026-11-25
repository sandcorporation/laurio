import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 저장 중 단추는 `disabled` 가 아니라 `aria-disabled` 라 눌린 단추의 초점이 BODY 로 떨어지지 않는다(#1517 취향2).
for (const [name, viewport] of [
  ["데스크톱", { width: 1280, height: 800 }],
  ["390px", { width: 390, height: 844 }],
] as const) {
  test(`${name}: 이름 저장 Enter → 저장 중에도 초점이 단추에 있고 aria-disabled·이름이 읽힌다`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const seed = `busy-focus-${test.info().workerIndex}-${Date.now()}`;
    await establishClassroomSession(page, seed);
    const api = classroomApi(page);
    const created = await api.post("/api/backend/classroom/classes", {
      data: { name: `저장 ${Date.now()}`, instructor_display_name: "강사" },
    });
    const classId = (await created.json()).id as number;
    const joinCode = (await (await api.get(`/api/backend/classroom/classes/${classId}`)).json()).join_code as string;
    await api.post(`/api/backend/classroom/classes/${classId}/problems`, { data: { title: "문제", submission_formats: ["repository"] } });
    await page.context().clearCookies();
    await establishClassroomSession(page, `${seed}-p`);
    expect((await api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "처음이름" } })).ok()).toBeTruthy();

    await page.goto(`/classes/${classId}/problems/mine`);
    await page.getByTestId("my-display-name-edit").click();
    await page.getByTestId("my-display-name-input").fill("바뀐이름");

    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/api/backend/classroom/**", async (route) => {
      if (route.request().method() !== "GET") await gate;
      await route.continue();
    });

    const writes: string[] = [];
    page.on("request", (request) => {
      if (request.method() !== "GET" && request.url().includes("/api/backend/classroom/")) writes.push(request.url());
    });
    const save = page.getByTestId("my-display-name-submit");
    await save.focus();
    await page.keyboard.press("Enter");
    await expect(save).toHaveAccessibleName("저장하는 중...");
    await expect(save).toHaveAttribute("aria-disabled", "true");
    await expect(save).toBeFocused();
    // 저장 중 한 번 더 눌러도 두 번째 요청이 나가지 않는다 — 눌림이 막힌다.
    await page.keyboard.press("Enter");
    release();
    await expect(page.getByTestId("my-display-name")).toHaveText("바뀐이름");
    await expect(page.getByTestId("my-display-name-edit")).toBeFocused();
    expect(writes).toHaveLength(1);
  });
}
