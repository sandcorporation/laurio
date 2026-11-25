import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 12차 사용 리뷰 #1492-4 — 줄마다 같은 글자의 링크는 접근성 이름에 대상이 있다(보이는 글자는 이름의 앞머리 그대로).
test("문제 표의 「편집」「제출 현황」과 내 클래스의 「열기」·보관 줄의 두 링크가 대상을 이름에 담는다", async ({ page }) => {
  const stamp = `${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, `named-links-${stamp}`);
  const api = classroomApi(page);
  const className = `이름 링크 ${stamp}`;
  const created = await api.post("/api/backend/classroom/classes", {
    data: { name: className, instructor_display_name: "강사" },
  });
  const classId = (await created.json()).id as number;
  const titles = ["첫째 문제", "둘째 문제"];
  for (const title of titles) {
    const made = await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
      data: { title, submission_formats: ["repository"] },
    });
    await api.post(`/api/backend/classroom/classes/${classId}/problems/${(await made.json()).id}/open`);
  }
  const old = await api.post("/api/backend/classroom/classes", {
    data: { name: `지난 이름 링크 ${stamp}`, instructor_display_name: "강사" },
  });
  const oldId = (await old.json()).id as number;
  expect((await api.post(`/api/backend/classroom/classes/${oldId}/archive`)).ok()).toBeTruthy();

  await page.goto(`/classes/${classId}`);
  for (const title of titles) {
    await expect(page.getByRole("link", { name: `편집 ${title}`, exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: `제출 현황 ${title}`, exact: true })).toBeVisible();
  }
  // 보이는 글자는 그대로다.
  await expect(page.getByRole("link", { name: `편집 ${titles[0]}`, exact: true })).toHaveText("편집");

  await page.goto("/");
  const open = page.getByRole("link", { name: `열기 ${className}`, exact: true });
  await expect(open).toHaveText("열기");
  await expect(open).toHaveAttribute("href", `/classes/${classId}`);
  await expect(page.getByRole("link", { name: `지난 기록 보기 지난 이름 링크 ${stamp}`, exact: true })).toHaveText("지난 기록 보기");
  await expect(page.getByRole("link", { name: `복사해서 새 기수 열기 지난 이름 링크 ${stamp}`, exact: true })).toHaveText(
    "복사해서 새 기수 열기",
  );
});

test("템플릿 목록의 「미리보기」 링크가 템플릿 이름을 이름에 담는다", async ({ page }) => {
  const stamp = `${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, `named-links-tpl-${stamp}`);
  const api = classroomApi(page);
  const created = await api.post("/api/backend/classroom/classes", {
    data: { name: `템플릿 링크 ${stamp}`, instructor_display_name: "강사" },
  });
  const classId = (await created.json()).id as number;
  const title = `공개 문제 ${stamp}`;
  const made = await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
    data: { title, submission_formats: ["repository"] },
  });
  const problemId = (await made.json()).id as number;
  const published = await api.post(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/publish-template`,
    { data: { publisher_display_name: "공유하는 강사" } },
  );
  expect(published.ok()).toBeTruthy();

  await page.goto("/templates");
  const preview = page.getByRole("link", { name: `미리보기 ${title}`, exact: true });
  await expect(preview).toHaveText("미리보기");
});
