import { type BrowserContext, expect, test } from "@playwright/test";

import { runSeed } from "../lib/seed-http";
import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 「최근 제출」의 「전체」 → 「제출」 화면, 「채점 실패」 시도의 「다시 채점」(#1317). 확인 창을 거쳐 걸면
// 상주 grader 가 정정을 돌리고 화면이 신호로 다시 읽으며, 새로고침해도 그 줄은 정정된 판정(통과)이고 버튼이 없다.
// 「채점 실패」 점수는 흉내 채점기가 내지 않으므로 키 없이 낸 시도(채점 대기)에 시드로 심고, 그 뒤에 키를 넣는다 —
// 정정은 키가 있어야 돈다. 체크리스트 문구를 저장소 URL 에 심어 두면 흉내 채점기가 통과시킨다.
// 준비(클래스·제출·시드·키)는 시험 한도(3초) 밖 beforeAll 에서 한다 — 한 시험으로 걸으면 CI 에서 3초를 넘었다.
test.describe.configure({ mode: "serial" });

type State = Awaited<ReturnType<BrowserContext["storageState"]>>;
let ownerState: State;
let classId: number;
let submissionId: number;

test.beforeAll(async ({ browser }) => {
  test.setTimeout(30_000);
  const seed = `class-attempts-regrade-${test.info().workerIndex}-${Date.now()}`;
  const marker = `codemit-e2e-marker-${test.info().workerIndex}-${Date.now()}`;

  const owner = await browser.newContext();
  const ownerPage = await owner.newPage();
  await establishClassroomSession(ownerPage, seed);
  const api = classroomApi(ownerPage);
  classId = (
    await (
      await api.post("/api/backend/classroom/classes", {
        data: { name: `다시 채점 ${Date.now()}`, instructor_display_name: "강사" },
      })
    ).json()
  ).id as number;
  const problemId = (
    await (
      await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
        data: { title: "1주차", submission_formats: ["repository"] },
      })
    ).json()
  ).id as number;
  const base = `/api/backend/classroom/classes/${classId}/problems/${problemId}`;
  await api.post(`${base}/checklist-items`, { data: { label: marker, required: true } });
  await api.post(`${base}/open`);
  const joinCode = (await (await api.get(`/api/backend/classroom/classes/${classId}`)).json()).join_code as string;

  const member = await browser.newContext();
  const memberPage = await member.newPage();
  await establishClassroomSession(memberPage, `${seed}-a`);
  const memberApi = classroomApi(memberPage);
  await memberApi.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "서지우" } });
  const submitted = await memberApi.post(`${base}/submissions`, {
    data: { value: `https://github.com/octocat/${marker}`, submission_format: "repository" },
  });
  expect(submitted.ok()).toBeTruthy();
  submissionId = (await submitted.json()).id as number;
  await member.close();
  await runSeed("classroom-failed-score", { submission_id: submissionId });

  expect(
    (await api.put(`/api/backend/classroom/classes/${classId}/openai-key`, { data: { api_key: "sk-e2e-test-key" } })).ok(),
  ).toBeTruthy();
  ownerState = await owner.storageState();
  await owner.close();
});

test("「최근 제출」의 「전체」가 「제출」 화면을 열고, 「채점 실패」 줄에 「다시 채점」이 있다", async ({ browser }) => {
  const page = await (await browser.newContext({ storageState: ownerState })).newPage();
  await page.goto(`/classes/${classId}`);
  await page.getByTestId("recent-attempts-all").click();
  await expect(page.getByTestId("class-attempts-heading")).toHaveText("제출");
  const row = page.getByTestId(`class-attempt-${submissionId}`);
  await expect(row).toContainText("서지우");
  await expect(row).toContainText("채점 실패");
  await expect(page.getByTestId(`regrade-${submissionId}`)).toBeVisible();
});

// 키보드만으로(#1463 의 같은 결함) — 열리면 「취소」, Tab 은 창 안, Escape 로 닫히고 「다시 채점」 단추로 돌아온다.
test("「다시 채점」 확인 창은 초점이 안으로 들어가 갇히고 Escape 로 닫히며 단추로 돌아온다", async ({ browser }) => {
  const page = await (await browser.newContext({ storageState: ownerState })).newPage();
  await page.goto(`/classes/${classId}/submissions`);
  const opener = page.getByTestId(`regrade-${submissionId}`);
  // 줄마다 같은 글자의 단추 — 누구 것인지가 이름에 있다(#1478 3).
  await expect(opener).toHaveAccessibleName(/^다시 채점 서지우 1주차$/);
  await opener.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "다시 채점" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "취소" })).toBeFocused();
  // 낭독기는 이름과 함께 누구의 어느 문제인지·예상 금액을 듣는다(#1477).
  await expect(dialog).toHaveAccessibleDescription(/서지우 · 1주차\s*예상 금액 .*원/);
  for (const key of ["Tab", "Tab", "Tab", "Shift+Tab", "Shift+Tab", "Shift+Tab"]) {
    await page.keyboard.press(key);
    await expect(dialog.locator(":focus")).toHaveCount(1);
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
});

test("「다시 채점」은 확인 창을 거쳐 걸리고, 새로고침 뒤 그 줄은 정정된 판정이며 버튼이 없다", async ({ browser }) => {
  const page = await (await browser.newContext({ storageState: ownerState })).newPage();
  await page.goto(`/classes/${classId}/submissions`);
  const row = page.getByTestId(`class-attempt-${submissionId}`);
  await expect(row).toContainText("채점 실패");

  await page.getByTestId(`regrade-${submissionId}`).click();
  const dialog = page.getByTestId("regrade-dialog");
  await expect(dialog).toContainText("서지우 · 1주차");
  await expect(page.getByTestId("regrade-amount")).toContainText("원");
  await page.getByTestId("regrade-confirm").click();
  await expect(dialog).toBeHidden();
  const heading = page.getByTestId("class-attempts-heading");
  await expect(heading).toBeFocused();

  // 정정이 끝나면 grader 가 attempt-scored 를 내고 화면이 다시 읽는다 — 그다음 새로고침해도 그대로다.
  await expect(page.getByTestId(`regrade-${submissionId}`)).toHaveCount(0);
  await expect(row).not.toContainText("채점 실패");
  // 단추가 사라진 뒤에도 초점은 제목에 있다 — body 로 빠지지 않는다(#1471 ④).
  await expect(heading).toBeFocused();
  await page.reload();
  await expect(row).toContainText("통과");
  await expect(row).not.toContainText("채점 실패");
  await expect(page.getByTestId(`regrade-${submissionId}`)).toHaveCount(0);
});

test("줄을 누르면 정정된 현재 판정이 펼쳐지고, 다시 누르면 접히며, 쪽 넘김·다시 채점 단추는 그대로다 (#1334)", async ({ browser }) => {
  const page = await (await browser.newContext({ storageState: ownerState })).newPage();
  await page.goto(`/classes/${classId}/submissions`);
  const toggle = page.getByTestId(`class-attempt-${submissionId}-toggle`);
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId(`class-attempt-${submissionId}-verdicts`)).toHaveCount(0);

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId(`class-attempt-${submissionId}-verdicts`)).toBeVisible();
  await expect(page.getByTestId(`class-attempt-${submissionId}-corrected`)).toBeVisible();
  await expect(page.getByTestId(`class-attempt-${submissionId}-verdicts`)).toContainText("충족");

  await toggle.click();
  await expect(page.getByTestId(`class-attempt-${submissionId}-verdicts`)).toHaveCount(0);
});
