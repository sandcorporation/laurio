import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 내 클래스(#641, 시안 v2 Home). 순서는 「내가 가르치는 클래스 → 참여 중인 클래스 → 보관」,
// 가르치는 행은 「참여자 N명 · 문제 N개」 · 달성률 막대, 참여 중 행은 「강사 이름 · 문제 N개」 ·
// 「k/n 통과」 · 「문제 풀기」. 공동 강사 배지, 보관 행의 두 버튼, 머리에 설명 문장이 없는 것을 본다.
// 값 계산(null 조건·제외 규칙)은 백엔드 test_classroom_aggregates.py 가 고정한다.
test("내 클래스가 가르치는·참여 중·보관 순으로 수치와 함께 보인다", async ({ page }) => {
  const stamp = `${test.info().workerIndex}-${Date.now()}`;
  const me = `e2e-home-me-${stamp}`;
  const other = `e2e-home-other-${stamp}`;

  async function createClass(name: string, instructor: string): Promise<{ id: number; base: string }> {
    const created = await classroomApi(page).post("/api/backend/classroom/classes", {
      data: { name, instructor_display_name: instructor },
    });
    expect(created.ok()).toBeTruthy();
    const id = (await created.json()).id as number;
    return { id, base: `/api/backend/classroom/classes/${id}` };
  }
  async function openProblem(base: string, title: string) {
    const api = classroomApi(page);
    const made = await api.post(`${base}/problems`, { data: { title, submission_formats: ["repository"] } });
    const id = (await made.json()).id as number;
    await api.post(`${base}/problems/${id}/checklist-items`, { data: { label: "통과 조건", required: true } });
    expect((await api.post(`${base}/problems/${id}/open`)).ok()).toBeTruthy();
  }

  // 다른 강사가 연 클래스 둘 — 하나는 나를 공동 강사로, 하나는 내가 참여자로.
  await establishClassroomSession(page, other);
  const coClass = await createClass(`공동 ${stamp}`, "박소유");
  const joinedClass = await createClass(`참여 ${stamp}`, "박지훈");
  await openProblem(joinedClass.base, "문제 하나");
  await openProblem(joinedClass.base, "문제 둘");
  const token = (
    await (await classroomApi(page).post(`${coClass.base}/co-instructor-invites`)).json()
  ).token as string;
  const joinCode = (await (await classroomApi(page).get(joinedClass.base)).json()).join_code as string;

  await establishClassroomSession(page, me);
  expect(
    (await classroomApi(page).post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, {
      data: { display_name: "나공동" },
    })).ok(),
  ).toBeTruthy();
  expect(
    (await classroomApi(page).post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "나참여" } })).ok(),
  ).toBeTruthy();
  const own = await createClass(`내 클래스 ${stamp}`, "나");
  await openProblem(own.base, "내 문제");
  const old = await createClass(`지난 기수 ${stamp}`, "나");
  expect((await classroomApi(page).post(`${old.base}/archive`)).ok()).toBeTruthy();

  await page.goto("/");

  // 머리에 설명 문장이 없다.
  await expect(page.getByTestId("classroom-home-heading")).toHaveText("내 클래스");
  await expect(page.getByTestId("classroom-home-heading-note")).toHaveCount(0);

  // 가르치는 행 — 참여자(강사 제외) 0명 · 문제 1개, 제출이 없으니 달성률은 「—」, 마지막 제출 조각은 없다.
  const ownRow = page.getByTestId(`classroom-row-${own.id}`);
  await expect(ownRow.getByTestId(`classroom-row-${own.id}-stats`)).toHaveText("참여자 0명 · 문제 1개");
  await expect(ownRow.getByTestId(`classroom-row-${own.id}-rate`)).toContainText("—");
  await expect(ownRow.getByTestId(`classroom-row-${own.id}-open`)).toHaveText("열기");
  await expect(page.getByTestId(`classroom-row-${coClass.id}-co-instructor-badge`)).toBeVisible();

  // 참여 중 행 — 「강사 … · 문제 2개」, 「0/2 통과」, 「문제 풀기」는 참여자 화면으로.
  const joinedRow = page.getByTestId(`classroom-joined-row-${joinedClass.id}`);
  await expect(joinedRow).toContainText("강사 박지훈 · 문제 2개");
  await expect(joinedRow.getByTestId(`classroom-joined-row-${joinedClass.id}-progress`)).toContainText("0/2");
  await expect(joinedRow.getByTestId(`classroom-joined-row-${joinedClass.id}-solve`)).toHaveAttribute(
    "href",
    `/classes/${joinedClass.id}/problems/mine`,
  );

  // 보관 행 — 두 버튼.
  const archivedRow = page.getByTestId(`classroom-row-${old.id}`);
  await expect(archivedRow.getByTestId(`classroom-row-${old.id}-view`)).toHaveText("지난 기록 보기");
  await expect(archivedRow.getByTestId(`classroom-row-${old.id}-copy`)).toHaveText("복사해서 새 기수 열기");

  // 순서 — 가르치는 → 참여 중 → 보관.
  const headings = await page.locator("main h2").allTextContents();
  expect(headings.map((h) => h.trim())).toEqual(["내가 가르치는 클래스", "참여 중인 클래스", "보관"]);
});
