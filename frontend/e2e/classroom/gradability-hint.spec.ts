import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 채점이 확인할 수 있는 것을 항목 입력칸 아래 한 줄과 저장 뒤 경고로 알린다(#810). 판별은 백엔드의
// `gradability_hint` 한 자리다 — 여기서는 화면이 그 값을 그리는지, 그리고 저장을 막지 않는지만 본다.
// SCREENS_DIR 가 있으면 검토용 스크린샷을 남긴다(PR 검토 자료, 시험 판정과 무관).

const SCREENS = process.env.SCREENS_DIR;
// 스크린샷을 남길 때만 한도를 푼다 — 시험 판정이 아니라 검토 자료다.
if (SCREENS) test.setTimeout(30_000);

async function seedClass(page: import("@playwright/test").Page) {
  await establishClassroomSession(page, `gradability-${test.info().workerIndex}-${Date.now()}`);
  const api = classroomApi(page);
  const classResponse = await api.post("/api/backend/classroom/classes", {
    data: { name: `채점 안내 ${Date.now()}`, instructor_display_name: "강사" },
  });
  return { api, classId: (await classResponse.json()).id as number };
}

async function shoot(page: import("@playwright/test").Page, name: string) {
  if (!SCREENS) return;
  for (const [label, width, height] of [["desktop", 1440, 900], ["mobile", 390, 844]] as const) {
    await page.setViewportSize({ width, height });
    await page.screenshot({ path: `${SCREENS}/${name}-${label}.png`, fullPage: true });
  }
}

test("문제 만들기 — 입력칸 아래 한 줄이 서고, 걸린 항목은 만든 직후 상세 화면에서 경고가 선다", async ({ page }) => {
  const { classId } = await seedClass(page);
  await page.goto(`/classes/${classId}/problems/new`);
  await expect(page.getByTestId("new-problem-checklist-gradability-note")).toContainText("정적 내용만 확인합니다");
  await page.getByTestId("new-problem-title-input").fill("단축 URL 서비스");
  await page.getByTestId("new-problem-new-checklist-item-label-input").fill("공개 /숫자 주소가 실제로 리디렉션된다");
  await page.getByTestId("new-problem-new-checklist-item-submit").click();
  await shoot(page, "new-problem");
  await page.getByTestId("new-problem-submit").click();
  await expect(page.getByTestId("checklist-gradability-warnings")).toContainText("확인하지 못할 수 있습니다");
  await expect(page.getByTestId("checklist-items").locator("li")).toHaveCount(1);
});

test("문제 상세 — 항목을 더하면 걸린 것만 경고가 서고 저장은 막히지 않는다", async ({ page }) => {
  const { api, classId } = await seedClass(page);
  const created = await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
    data: { title: "단축 URL 서비스", submission_formats: ["source"], checklist_items: [{ label: "합을 출력한다", required: true }] },
  });
  const problemId = (await created.json()).id as number;

  await page.goto(`/classes/${classId}/problems/${problemId}`);
  await expect(page.getByTestId("checklist-gradability-note")).toContainText("정적 내용만 확인합니다");
  await expect(page.getByTestId("checklist-gradability-warnings")).toHaveCount(0);
  await page.getByTestId("new-checklist-item-label-input").fill("/숫자 경로를 리디렉션 응답으로 처리하는 코드가 있다");
  await page.getByTestId("new-checklist-item-submit").click();
  await expect(page.getByTestId("checklist-items").locator("li")).toHaveCount(2);
  await expect(page.getByTestId("checklist-gradability-warnings")).toHaveCount(0);
  await page.getByTestId("new-checklist-item-label-input").fill("배포 주소로 접속하면 열린다");
  await page.getByTestId("new-checklist-item-submit").click();
  await expect(page.getByTestId("checklist-gradability-warnings")).toContainText("배포 주소로 접속하면 열린다");
  await expect(page.getByTestId("checklist-items").locator("li")).toHaveCount(3);
  await shoot(page, "problem-detail");
});
