import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 클래스 상세의 참여자 탭(시안 v2, #634). 명단과 격자를 합친 한 표에서 내보내기까지 간다:
// ⋮ → 내보내기 → 확인 → 새로고침해도 「내보냄」. 내보내기는 서버 상태를 바꾸므로 화면만 보고 끝내지
// 않는다. 칸 모양·달성률 색 같은 판정은 백엔드 pytest 와 단위 시험이 고정한다. 준비는 API 로 직접 친다.

test("참여자 탭 — 한 표에서 가입일·통과 n/N 을 보고 내보내면 새로고침해도 내보냄이다", async ({ page }) => {
  const seed = `participants-tab-${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, seed);
  const api = classroomApi(page);

  const created = await api.post("/api/backend/classroom/classes", {
    data: { name: `참여자 탭 ${Date.now()}`, instructor_display_name: "강사" },
  });
  const classId = (await created.json()).id as number;
  const joinCode = (await (await api.get(`/api/backend/classroom/classes/${classId}`)).json()).join_code as string;
  const problemResponse = await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
    data: { title: "참여자 탭 문제", submission_formats: ["repository"] },
  });
  const problemId = (await problemResponse.json()).id as number;
  await api.post(`/api/backend/classroom/classes/${classId}/problems/${problemId}/checklist-items`, {
    data: { label: "통과 조건", required: true },
  });
  await api.post(`/api/backend/classroom/classes/${classId}/problems/${problemId}/open`);

  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-participant`);
  const joined = await api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "나가는사람" } });
  expect(joined.ok()).toBeTruthy();
  await page.context().clearCookies();
  await establishClassroomSession(page, seed);

  await page.goto(`/classes/${classId}?tab=participants`);
  const members = (await (await api.get(`/api/backend/classroom/classes/${classId}/members`)).json()) as {
    id: number;
    display_name: string;
  }[];
  const memberId = members.find((m) => m.display_name === "나가는사람")!.id;
  await expect(page.getByTestId(`participant-row-${memberId}-name`)).toContainText("나가는사람");
  await expect(page.getByTestId(`participant-row-${memberId}-joined-at`)).toContainText("가입");
  await expect(page.getByTestId(`participant-row-${memberId}-passed`)).toHaveText("0/1");
  await expect(page.getByTestId(`participant-cell-${memberId}-${problemId}`)).toHaveAttribute("data-status", "not_submitted");

  await page.getByTestId(`participant-row-${memberId}-menu`).click();
  await page.getByTestId(`participant-row-${memberId}-expel`).click();
  await expect(page.getByTestId("expel-dialog")).toContainText("나가는사람");
  await page.getByTestId("expel-confirm").click();
  await expect(page.getByTestId(`participant-row-${memberId}-expelled-badge`)).toBeVisible();
  await expect(page.getByTestId(`participant-row-${memberId}-menu`)).toHaveCount(0);

  await page.reload();
  await expect(page.getByTestId(`participant-row-${memberId}-expelled-badge`)).toBeVisible();

  // 예전 명단 주소는 탭으로 돌아온다.
  await page.goto(`/classes/${classId}/members`);
  await expect(page).toHaveURL(`/classes/${classId}?tab=participants`);
  await expect(page.getByTestId("participants-table")).toBeVisible();
});
