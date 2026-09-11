import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 공개된 템플릿을 목록에서 찾아 내 클래스로 가져온다 (#316/#318).
//
// 이번 작업에서 새로 생기는 유일한 유저스토리다 — 마크다운·체크리스트는
// 백엔드와 단위 테스트가 같은 사실을 더 짧게 고정하므로 e2e로 남기지 않는다
// (#312 Testing Decisions). 강의실은 자기 로그인이 없어(ADR-0038) 공개 앱에
// 세션을 세운 뒤 그 쿠키를 이 오리진에 심는다(`lib/cross-app-session.ts`).
//
// 시임 규약(ADR-0017/0021)을 그대로 따른다 — 브라우저로 걷는 것은 검증
// 대상(검색·미리보기·가져오기)뿐이고, 원본 문제·체크리스트를 만들고
// 템플릿으로 공개하는 준비 단계는 `request`로 API를 직접 친다.

test("강사가 다른 강사의 템플릿을 목록에서 찾아 자기 클래스로 가져온다", async ({ page }) => {
  const publisherSeed = `template-publisher-${test.info().workerIndex}-${Date.now()}`;
  const importerSeed = `template-importer-${test.info().workerIndex}-${Date.now()}`;
  const title = `공유용 Todo API ${Date.now()}`;

  // --- 준비: 공개자가 문제 하나를 만들고 템플릿으로 공개한다 -------------
  await establishClassroomSession(page, publisherSeed);
  const api = classroomApi(page);

  const classResponse = await api.post("/api/backend/classroom/classes", {
    data: { name: "공개용 클래스", instructor_display_name: "공유하는 강사" },
  });
  expect(classResponse.ok()).toBeTruthy();
  const classId = (await classResponse.json()).id as number;

  const problemResponse = await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
    data: { title, description: "테스트가 통과해야 합니다.", submission_format: "source" },
  });
  expect(problemResponse.ok()).toBeTruthy();
  const problemId = (await problemResponse.json()).id as number;

  await api.post(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/checklist-items`,
    { data: { label: "테스트가 통과한다", required: true } },
  );

  const publishResponse = await api.post(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/publish-template`,
    { data: { publisher_display_name: "공유하는 강사" } },
  );
  expect(publishResponse.ok()).toBeTruthy();

  // --- 검증 대상: 가져오는 강사가 목록에서 찾아 가져온다 -----------------
  await page.context().clearCookies();
  await establishClassroomSession(page, importerSeed);

  const targetClassResponse = await api.post("/api/backend/classroom/classes", {
    data: { name: "내 클래스", instructor_display_name: "가져오는 강사" },
  });
  expect(targetClassResponse.ok()).toBeTruthy();
  const targetClassId = (await targetClassResponse.json()).id as number;

  await page.goto("/templates");
  await page.getByTestId("template-search-input").fill(title);
  await page.getByTestId("template-search-submit").click();

  await expect(page.getByTestId("problem-templates-list")).toContainText(title);
  await page.getByRole("link", { name: title }).click();

  await expect(page.getByTestId("template-preview-heading")).toHaveText(title);
  await expect(page.getByTestId("template-preview-checklist")).toContainText("테스트가 통과한다");

  await page.getByTestId("template-import-target-select").selectOption(String(targetClassId));
  await page.getByTestId("template-import-submit").click();

  await expect(page).toHaveURL(new RegExp(`/classes/${targetClassId}/problems/\\d+$`));
  await expect(page.getByTestId("edit-problem-title-input")).toHaveValue(title);
  // 편집 화면은 라벨을 편집 칸(`<input defaultValue>`)으로 그린다 — 텍스트가 아니라 값이라
  // `toContainText` 로는 안 보인다. 가져온 항목의 id 는 미리 알 수 없어 역할로 잡는다(같은
  // 행의 「필수」는 체크박스라 textbox 에 섞이지 않는다).
  await expect(page.getByTestId("checklist-items").getByRole("textbox")).toHaveValue("테스트가 통과한다");
});
