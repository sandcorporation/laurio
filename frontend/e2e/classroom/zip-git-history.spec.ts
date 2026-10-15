import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — zip 에는 Git 기록이 없다(#587). 소스를 받는 문제의 필수 항목이 커밋을 물으면 강사 편집
// 화면에 경고와 고칠 길이, 참여자 제출 화면의 zip 칸에 눈에 띄는 안내가 선다. 판정은 백엔드다 —
// 여기서는 경고가 서는 문제와 서지 않는 문제를 둘 다 만들어 화면이 그 값을 그대로 그리는지 본다.

async function seedClass(page: Page, seed: string) {
  await establishClassroomSession(page, seed);
  const api = classroomApi(page);
  const classResponse = await api.post("/api/backend/classroom/classes", {
    data: { name: `zip 경고 ${Date.now()}`, instructor_display_name: "강사" },
  });
  expect(classResponse.ok()).toBeTruthy();
  const classId = (await classResponse.json()).id as number;
  async function problem(submission_formats: string[], labels: string[], open = false) {
    const response = await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
      data: {
        title: `문제 ${labels[0]}`,
        submission_formats,
        checklist_items: labels.map((label) => ({ label, required: true })),
        open,
      },
    });
    expect(response.ok()).toBeTruthy();
    return (await response.json()) as { id: number; checklist_items: { id: number }[] };
  }
  return { api, classId, problem };
}

test("커밋을 묻는 항목이 있으면 편집 화면에 경고가 서고, 「받는 형식을 저장소만으로」가 저장된다", async ({ page }) => {
  const { classId, problem } = await seedClass(page, `zip-git-repo-only-${test.info().workerIndex}-${Date.now()}`);
  const flagged = await problem(["source", "repository"], ["합을 출력한다", "커밋 메시지를 남겼다"]);
  const plain = await problem(["source"], ["합을 출력한다"]);

  await page.goto(`/classes/${classId}/problems/${plain.id}`);
  await expect(page.getByTestId("checklist-items")).toBeVisible();
  await expect(page.getByTestId("zip-git-history-warning")).toHaveCount(0);

  await page.goto(`/classes/${classId}/problems/${flagged.id}`);
  const warning = page.getByTestId("zip-git-history-warning");
  await expect(warning).toContainText("zip 제출에는 Git 기록이 들어가지 않습니다.");
  await expect(page.getByTestId(`zip-git-history-item-${flagged.checklist_items[1].id}`)).toContainText("커밋 메시지를 남겼다");
  await expect(page.getByTestId(`zip-git-history-item-${flagged.checklist_items[0].id}`)).toHaveCount(0);

  await page.getByTestId("zip-git-history-repository-only").click();
  await expect(warning).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("edit-problem-format-repository")).toBeChecked();
  await expect(page.getByTestId("edit-problem-format-source")).not.toBeChecked();
  await expect(page.getByTestId("zip-git-history-warning")).toHaveCount(0);
});

test("「이 항목을 선택으로」가 그 항목을 선택으로 저장하고 경고가 걷힌다", async ({ page }) => {
  const { classId, problem } = await seedClass(page, `zip-git-optional-${test.info().workerIndex}-${Date.now()}`);
  const flagged = await problem(["source"], ["합을 출력한다", "브랜치를 나눠 작업했다"]);
  const itemId = flagged.checklist_items[1].id;

  await page.goto(`/classes/${classId}/problems/${flagged.id}`);
  await page.getByTestId(`zip-git-history-make-optional-${itemId}`).click();
  await expect(page.getByTestId("zip-git-history-warning")).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("checklist-items")).toBeVisible();
  await expect(page.getByTestId("zip-git-history-warning")).toHaveCount(0);
});

test("참여자가 zip 을 고르면 Git 기록 안내가 보이고, 커밋을 묻는 문제면 경고 띠로 선다", async ({ page, browser }) => {
  const seed = `zip-git-participant-${test.info().workerIndex}-${Date.now()}`;
  const instructorContext = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const instructorPage = await instructorContext.newPage();
  const { api, classId, problem } = await seedClass(instructorPage, seed);
  const flagged = await problem(["source", "repository"], ["커밋 메시지를 남겼다"], true);
  const plain = await problem(["source"], ["합을 출력한다"], true);
  const joinCode = (await (await api.get(`/api/backend/classroom/classes/${classId}`)).json()).join_code as string;
  await establishClassroomSession(page, `${seed}-participant`);
  expect(
    (await classroomApi(page).post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "서지우" } })).ok(),
  ).toBeTruthy();

  await page.goto(`/classes/${classId}/problems/${plain.id}/submit`);
  const side = page.getByTestId("my-problem-side");
  await expect(side.getByTestId("zip-git-history-note")).toHaveText(
    "zip 에는 Git 기록(.git)이 들어가지 않습니다. 커밋 기록을 보여야 하는 문제는 저장소로 내세요.",
  );
  await expect(side.getByTestId("zip-git-history-warning")).toHaveCount(0);

  await page.goto(`/classes/${classId}/problems/${flagged.id}/submit`);
  await side.getByTestId("submission-format-option-source").click();
  await expect(side.getByTestId("zip-git-history-warning")).toContainText("이 문제는 커밋 기록을 봅니다.");
  await side.getByTestId("zip-git-history-use-repository").click();
  await expect(side.getByTestId("repository-url-input")).toBeVisible();
  await instructorContext.close();
});
