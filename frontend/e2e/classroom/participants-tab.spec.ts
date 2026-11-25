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
  // 초안은 열리지 않았으니 n/N 의 N 에 들지 않고 달성률은 「—」다(#669).
  const draftId = (await (
    await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
      data: { title: "초안 문제", submission_formats: ["repository"] },
    })
  ).json()).id as number;

  // 강사가 자기 클래스에 참여자로도 들어온다 — 그 행은 「강사 본인」이고 내보낼 수 없다.
  expect((await api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "강사" } })).ok()).toBeTruthy();

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
  await expect(page.getByTestId(`participant-row-${memberId}-joined-at`)).toHaveText(/^\d{1,2}\/\d{1,2} 가입$/);
  await expect(page.getByTestId(`participant-row-${memberId}-passed`)).toHaveText("0/1");
  await expect(page.getByTestId(`participants-header-problem-${draftId}-draft-badge`)).toHaveText("초안");
  await expect(page.getByTestId(`participants-achievement-${draftId}`)).toHaveText("—");
  // 강사 본인 행은 내보낼 수 없다 — ⋮ 가 없다.
  const instructorId = members.find((m) => m.display_name === "강사")!.id;
  await expect(page.getByTestId(`participant-row-${instructorId}-instructor-badge`)).toBeVisible();
  await expect(page.getByTestId(`participant-row-${instructorId}-menu`)).toHaveCount(0);
  await expect(page.getByTestId(`participant-cell-${memberId}-${problemId}`)).toHaveAttribute("data-status", "not_submitted");
  // 칸은 모양으로만 그리니 뜻은 범례·툴팁·표식 이름이 진다(#1398). 이름은 칸 **안**의 표식에 있어야 칸 내용을 읽는
  // 스크린리더에도 빈 칸이 아니다.
  const cell = page.getByTestId(`participant-cell-${memberId}-${problemId}`);
  await expect(page.getByTestId("participants-legend-not_submitted")).toHaveText("미제출");
  // 범례는 긴 표 아래가 아니라 위에 있다(#1422).
  const legendTop = (await page.getByTestId("participants-legend").boundingBox())!.y;
  const tableTop = (await page.getByTestId("participants-table").boundingBox())!.y;
  expect(legendTop).toBeLessThan(tableTop);
  await expect(page.getByTestId("participants-legend-attempted_not_passed")).toHaveText("시도했으나 미통과");
  await expect(cell).toHaveAttribute("title", "미제출");
  await expect(cell.getByRole("img", { name: "미제출", exact: true })).toBeVisible();

  await page.getByTestId(`participant-row-${memberId}-menu`).click();
  await page.getByTestId(`participant-row-${memberId}-expel`).click();
  await expect(page.getByTestId("expel-dialog")).toContainText("나가는사람");
  // 낭독기는 이름과 함께 본문을 듣는다 — 누가 어떻게 되는지(#1477).
  await expect(page.getByRole("dialog", { name: "참여자 내보내기" })).toHaveAccessibleDescription(
    /나가는사람님을 내보냅니다.*이름과 지난 제출·판정은 그대로 남습니다/,
  );
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

// 스스로 나간 공동 강사는 「내보냄」이 아니라 「나감」이다(#1492-5). 참여자였던 사람이 공동 강사가 됐다가 떠나면
// 참여자 행도 닫히는데(`co_instructors.depart`), 그것은 누가 내보낸 것이 아니다. 참여자 표·내 클래스·제출 안내
// 셋이 같은 값(`left`·`submit_blocked_reason: "left"`)을 읽는다. 390px 에서 본다 — 넓은 화면은 같은 마크업이다.
test("참여자 탭 — 스스로 나간 공동 강사는 「나감」이고 본인 화면도 내보내졌다고 하지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const seed = `participants-left-${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, seed);
  const api = classroomApi(page);
  const base = `/api/backend/classroom/classes`;
  const classId = (await (
    await api.post(base, { data: { name: `나간 조교 ${Date.now()}`, instructor_display_name: "강사" } })
  ).json()).id as number;
  const problemId = (await (
    await api.post(`${base}/${classId}/problems`, { data: { title: "나감 문제", submission_formats: ["repository"] } })
  ).json()).id as number;
  await api.post(`${base}/${classId}/problems/${problemId}/checklist-items`, { data: { label: "통과 조건", required: true } });
  expect((await api.post(`${base}/${classId}/problems/${problemId}/open`)).ok()).toBeTruthy();
  const joinCode = (await (await api.get(`${base}/${classId}`)).json()).join_code as string;
  const token = (await (await api.post(`${base}/${classId}/co-instructor-invites`)).json()).token as string;

  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-helper`);
  expect((await api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "조교였던학생" } })).ok()).toBeTruthy();
  expect(
    (await api.post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, { data: { display_name: "조교" } })).ok(),
  ).toBeTruthy();
  expect((await api.post(`${base}/${classId}/instructors/me/leave`)).status()).toBe(204);

  // 나간 본인 — 내 클래스 줄과 제출 안내.
  await page.goto("/");
  const joinedRow = page.getByTestId(`classroom-joined-row-${classId}`);
  await expect(joinedRow.getByTestId(`classroom-joined-row-${classId}-left-badge`)).toHaveText("나감");
  await expect(joinedRow).not.toContainText("내보내짐");
  await page.goto(`/classes/${classId}/problems/${problemId}/submit`);
  const note = page.getByRole("alert").filter({ hasText: "이 클래스에서 나가 새로 제출할 수 없습니다." });
  await expect(note).toBeVisible();
  await expect(page.getByTestId("member-expelled-note")).toHaveCount(0);
  await expect(page.getByTestId("submit-repository")).toHaveCount(0);

  // 소유자 — 참여자 표. 낭독기는 칸 내용으로 「나감」을 듣는다.
  await page.context().clearCookies();
  await establishClassroomSession(page, seed);
  const members = (await (await api.get(`${base}/${classId}/members`)).json()) as { id: number; display_name: string }[];
  const memberId = members.find((m) => m.display_name === "조교였던학생")!.id;
  await page.goto(`/classes/${classId}?tab=participants`);
  const nameCell = page.getByTestId(`participant-row-${memberId}-name`);
  await expect(page.getByRole("cell", { name: /조교였던학생\s*나감/ })).toBeVisible();
  await expect(page.getByTestId(`participant-row-${memberId}-left-badge`)).toHaveText("나감");
  await expect(page.getByTestId(`participant-row-${memberId}-expelled-badge`)).toHaveCount(0);
  await expect(nameCell).not.toContainText("내보냄");
  // 취소선은 「내보냄」만의 표시다.
  await expect(nameCell.getByText("조교였던학생", { exact: true })).not.toHaveCSS("text-decoration-line", "line-through");
  await expect(page.getByTestId(`participant-row-${memberId}-menu`)).toHaveCount(0);
});

// 키보드만으로 — 행 메뉴(⋮)는 WAI-ARIA 메뉴 단추 꼴(#1465 1번), 내보내기 확인창은 초점이 안으로 들어가 갇히고
// Escape 로 닫히며 ⋮ 로 돌아온다(#1463).
test("참여자 탭 — 행 메뉴와 내보내기 확인창은 키보드만으로 다룬다", async ({ page }) => {
  const seed = `participants-kbd-${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, seed);
  const api = classroomApi(page);
  const created = await api.post("/api/backend/classroom/classes", {
    data: { name: `참여자 키보드 ${Date.now()}`, instructor_display_name: "강사" },
  });
  const classId = (await created.json()).id as number;
  const joinCode = (await (await api.get(`/api/backend/classroom/classes/${classId}`)).json()).join_code as string;
  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-p`);
  expect((await api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "키보드참여자" } })).ok()).toBeTruthy();
  await page.context().clearCookies();
  await establishClassroomSession(page, seed);

  await page.goto(`/classes/${classId}?tab=participants`);
  const members = (await (await api.get(`/api/backend/classroom/classes/${classId}/members`)).json()) as {
    id: number;
    display_name: string;
  }[];
  const id = members.find((m) => m.display_name === "키보드참여자")!.id;
  const trigger = page.getByTestId(`participant-row-${id}-menu`);
  const item = page.getByRole("menuitem", { name: "내보내기" });

  // 메뉴: 열면 첫 항목에 초점, ↑↓·Home/End, Escape 는 닫고 ⋮ 로.
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("menu", { name: "키보드참여자 메뉴" })).toBeVisible();
  await expect(item).toBeFocused();
  for (const key of ["ArrowDown", "ArrowUp", "End", "Home"]) {
    await page.keyboard.press(key);
    await expect(item).toBeFocused();
  }
  await page.keyboard.press("Escape");
  await expect(item).toHaveCount(0);
  await expect(trigger).toBeFocused();
  // 항목에서 Tab 은 메뉴를 닫는다.
  await page.keyboard.press("Enter");
  await expect(item).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(item).toHaveCount(0);

  // 확인창: 열리면 「취소」, Tab 을 여러 번 눌러도 창 안, Escape 로 닫히고 ⋮ 로 돌아온다.
  await trigger.focus();
  await page.keyboard.press("Enter");
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "참여자 내보내기" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "취소" })).toBeFocused();
  for (const shift of [false, false, false, true, true, true, true]) {
    await page.keyboard.press(shift ? "Shift+Tab" : "Tab");
    await expect(dialog.locator(":focus")).toHaveCount(1);
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
});
