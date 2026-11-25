import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 참여자 제출 화면(#640, 시안 v2 Submit). 형식 선택(#373) → 저장소 주소 → 제출 → 「내 시도」에 줄이 생긴다.
// 통과·미통과와 판정 낱말은 상주 grader 때문에 e2e 에서 붙들기 어렵다 — 키 없는 클래스로 「채점 대기」 줄을 만든다.
// 판정을 품는 체크리스트 카드의 계산은 단위 시험(latest-attempts)과 scoring-notification 이 맡는다.
test("형식을 고르고 저장소를 내면 내 시도에 줄이 생긴다", async ({ page, browser }) => {
  const seed = `participant-submit-${test.info().workerIndex}-${Date.now()}`;

  const instructorContext = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const instructorPage = await instructorContext.newPage();
  await establishClassroomSession(instructorPage, seed);
  const api = classroomApi(instructorPage);

  const classId = (
    await (
      await api.post("/api/backend/classroom/classes", {
        data: { name: `제출 테스트 ${Date.now()}`, instructor_display_name: "강사" },
      })
    ).json()
  ).id as number;
  const base = `/api/backend/classroom/classes/${classId}`;
  const problemId = (
    await (
      await api.post(`${base}/problems`, {
        data: { title: "목록 그리기", submission_formats: ["source", "repository"] },
      })
    ).json()
  ).id as number;
  expect(
    (await api.post(`${base}/problems/${problemId}/checklist-items`, { data: { label: "목록을 그린다", required: true } })).ok(),
  ).toBeTruthy();
  // 강사가 아직 초안인 문제를 학생 화면으로 열면 띠가 배지 둘이다(#660·#670).
  await instructorPage.goto(`/classes/${classId}/problems/${problemId}/submit`);
  await expect(instructorPage.getByTestId("instructor-viewing-banner")).toContainText("강사로 보는 중");
  await expect(instructorPage.getByTestId("instructor-viewing-banner-draft")).toHaveText("초안");
  expect((await api.post(`${base}/problems/${problemId}/open`)).ok()).toBeTruthy();

  const joinCode = (await (await api.get(base)).json()).join_code as string;
  await establishClassroomSession(page, `${seed}-participant`);
  expect(
    (await classroomApi(page).post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "서지우" } })).ok(),
  ).toBeTruthy();

  await page.goto(`/classes/${classId}/problems/${problemId}/submit`);

  await expect(page.getByTestId("my-problem-title")).toHaveText("목록 그리기");
  await expect(page.getByTestId("my-problem-passed-status")).toHaveText("아직 미통과");
  await expect(page.getByTestId("my-problem-back-link")).toHaveAttribute("href", `/classes/${classId}/problems/mine`);
  await expect(page.getByTestId("submissions-empty-state")).toBeVisible();
  // 체크리스트는 아직 판정이 없어 항목만 있다.
  await expect(page.getByTestId("my-problem-checklist-badge")).toHaveCount(0);
  await expect(page.getByTestId("my-problem-checklist")).toContainText("목록을 그린다");

  // 둘 다 열린 문제는 형식을 먼저 고른다 — zip 은 드롭 칸, 저장소는 주소 칸이다.
  const side = page.getByTestId("my-problem-side");
  await side.getByTestId("submission-format-option-source").click();
  await expect(side.getByTestId("source-file-input")).toBeAttached();
  await expect(side.getByTestId("source-file-max-size")).toHaveText("최대 50MB");
  await side.getByTestId("submission-format-change").click();
  await side.getByTestId("submission-format-option-repository").click();
  await side.getByTestId("repository-url-input").fill("https://github.com/octocat/e2e-submit");
  await side.getByTestId("submit-repository").click();

  const rows = page.getByTestId("submissions-list").locator(":scope > li");
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("시도 1");
  await expect(page.getByTestId("my-problem-progress-count")).toBeVisible();
});

// 390px(#1376) — 채점 대기 사유가 잘리지 않고, 제출 칸은 링크 한 번이면 닿는다.
test("좁은 폭에서 대기 사유가 다 보이고 링크로 제출 칸에 닿는다", async ({ page, browser }) => {
  const seed = `participant-submit-narrow-${test.info().workerIndex}-${Date.now()}`;

  const instructorContext = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const instructorPage = await instructorContext.newPage();
  await establishClassroomSession(instructorPage, seed);
  const api = classroomApi(instructorPage);

  const classId = (
    await (
      await api.post("/api/backend/classroom/classes", {
        data: { name: `좁은 폭 제출 ${Date.now()}`, instructor_display_name: "강사" },
      })
    ).json()
  ).id as number;
  const base = `/api/backend/classroom/classes/${classId}`;
  const problemId = (
    await (await api.post(`${base}/problems`, { data: { title: "목록 그리기", submission_formats: ["repository"] } })).json()
  ).id as number;
  // 첫 화면 밖으로 제출 칸이 밀리도록 체크리스트를 쌓는다.
  for (let index = 1; index <= 8; index += 1) {
    expect(
      (await api.post(`${base}/problems/${problemId}/checklist-items`, { data: { label: `항목 ${index}`, required: true } })).ok(),
    ).toBeTruthy();
  }
  expect((await api.post(`${base}/problems/${problemId}/open`)).ok()).toBeTruthy();

  const joinCode = (await (await api.get(base)).json()).join_code as string;
  await establishClassroomSession(page, `${seed}-participant`);
  const participant = classroomApi(page);
  expect(
    (await participant.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "서지우" } })).ok(),
  ).toBeTruthy();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/classes/${classId}/problems/${problemId}/submit`);

  const submitForm = page.getByTestId("submit-form-area");
  await expect(submitForm).not.toBeInViewport();
  await page.getByTestId("my-problem-submit-jump").click();
  await expect(submitForm).toBeInViewport();

  await page.getByTestId("repository-url-input").fill("https://github.com/octocat/e2e-submit");
  await page.getByTestId("submit-repository").click();

  // 키 없는 클래스라 시도는 채점 대기에 머문다.
  const note = page.getByTestId(/^submission-row-\d+-no-api-key-note$/);
  await expect(note).toHaveText("강사의 채점 설정 때문에 멈췄습니다 — 다시 낼 필요 없습니다");
  expect(
    await note.evaluate((element) => ({
      clipped: element.scrollWidth > element.clientWidth,
      pageOverflows: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    })),
  ).toEqual({ clipped: false, pageOverflows: false });
});
