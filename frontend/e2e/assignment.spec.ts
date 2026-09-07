import { expect, test } from "@playwright/test";

import { establishDeveloperSession } from "./lib/session";
import { runInternalScan, runSeed } from "./lib/seed-http";

// Assignment 전체 기능의 유일한 공개 앱 e2e (#210, ADR-0028/0029). CLAUDE.md
// "남길 것"의 「앱마다 유저스토리 한 벌」— 강사가 과제를 만들고 열어 InviteCode를
// 얻고, 학생이 그 코드로 들어와 제출하고, 마감 후 점수를 보는 한 벌이다. 프록시
// 허용목록(위험 3, `/api/assignments`·`/api/submissions`)이 실제로 막는지는 이
// 흐름이 그 경로들을 실제로 지나가며 함께 덮는다.
//
// Assignment 3(#207)·4(#208)가 만든 화면(과제 만들기·열기·InviteCode 진입·제출)과
// 6(#210)이 만든 화면(마감 후 학생의 채점 결과)을 한 번에 걷는다 — 그 사이(5, 7 —
// 재발급·소스 열람)는 각자의 체인이 자기 스펙을 갖는다(스코프 펜스, 이 스펙에
// 섞지 않는다).
//
// **celery가 이 e2e 잡에 없다**(#40) — 그래서 마감이 지나도 저절로 전이·채점되지
// 않는다. 진짜 시간이 지나가게 기다린 뒤(`waitForTimeout`), `runInternalScan`으로
// `assignment-close`·`submission-scoring`을 직접 쏜다 — 시연 지침(CLAUDE.md "tick은
// 시간을 앞당기지 않는다")과 같은 이유로, 시계를 조작하지 않고 실제 마감 시각을
// 실제로 지나가게 한다.
//
// **`ClockOverride`(#3, ADR-0003)를 쓰지 않는 이유는 공유 DB가 아니다 — CI는
// 잡마다 격리된 스택을 쓴다.** 그 대신: (1) `ClockOverride`는 HTTP로 노출된 적이
// 없다 — 새 내부 엔드포인트를 이 스펙 하나를 위해 여는 것은 시계라는 전역 자원에
// 손대는 표면을 늘리는 과잉이다. (2) 대안(과제를 편 뒤 곧바로 `deadline_at`을
// 과거로 PATCH)은 그 순간 제출이 아직 0건이라 지금은 통과하지만, #209(이 스펙과
// 동시에 진행 중)가 "제출이 있으면 고칠 수 없다"를 걸면 학생의 제출이 그 PATCH
// 보다 먼저 있어야 이 흐름이 뜻이 있으므로 순서를 못 바꾼다 — 앞으로 깨질 전제를
// 심는 셈이다. 그래서 실제 시간 경과를 택하되, 아래 창을 느슨하게 잡아 CI가 느려도
// "학생이 제출을 누르기 전에 마감이 지나버리는" 진짜 flake 원인을 없앤다.

function toDatetimeLocalInput(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

test("강사가 과제를 열어 InviteCode를 주고, 학생이 제출하고, 마감 후 점수를 본다", async ({
  page,
}) => {
  // 기본 테스트 타임아웃(30초)이 아래 실제 대기(마감을 실제로 흘려보낸다)를
  // 못 견딘다 — 넉넉히 늘린다.
  test.setTimeout(150_000);

  // 자격 있는 Sponsor와 학생 계정 — 둘 다 고정된 (provider, provider_uid)로
  // 귀결되는 멱등 시드다(seed_e2e_assignment_sponsor_and_student.py). username은
  // "kakao:<provider_uid>" 모양이라(accounts.api._username_for) 그 접두어를
  // 떼면 `establishDeveloperSession`이 받는 seed 값이 된다.
  const seeded = (await runSeed("assignment-sponsor-and-student")) as {
    sponsor_username: string;
    student_username: string;
  };
  const sponsorSeed = seeded.sponsor_username.replace(/^kakao:/, "");
  const studentSeed = seeded.student_username.replace(/^kakao:/, "");

  // 창을 준다 — 아래 브라우저 조작(로그인 둘·폼 채우기 둘·업로드 하나) 전부가
  // 이 시각 이전에 끝나야 제출이 막히지 않는다(`_reject_if_past_deadline`).
  // **진짜 flake 원인은 이 창이 너무 짧아 느린 CI에서 학생이 제출 버튼을
  // 누르기 전에 마감이 지나버리는 것**이지 뒤이은 `waitForTimeout` 자체가
  // 아니다 — 그래서 넉넉히 45초를 준다(총 타임아웃 150초 안에 여유 있게
  // 들어온다).
  const deadlineAt = new Date(Date.now() + 45_000);

  // 1) 강사 — 과제를 만들고 연다.
  await establishDeveloperSession(page, sponsorSeed);
  await page.goto("/console/assignments/new");
  await expect(page.getByTestId("new-assignment-heading")).toBeVisible();

  const title = `[E2E] 과제 흐름 ${Date.now()}`;
  await page.getByTestId("new-assignment-title").fill(title);
  // 산출물 종류 — 어느 것이든 하나면 된다(스펙이 특정 종류를 요구하지 않는다).
  await page.locator('input[data-testid^="new-assignment-deliverable-type-"]').first().check();
  await page.getByTestId("new-assignment-deadline").fill(toDatetimeLocalInput(deadlineAt));
  await page.getByTestId("new-assignment-submit").click();

  await expect(page).toHaveURL(/\/console\/assignments\/\d+$/, { timeout: 10_000 });
  await expect(page.getByTestId("assignment-detail-heading")).toHaveText(title);
  const assignmentDetailUrl = page.url();

  await page.getByTestId("assignment-open-button").click();
  await expect(page.getByTestId("assignment-invite-code")).toBeVisible({ timeout: 10_000 });
  const inviteCode = (await page.getByTestId("assignment-invite-code").innerText()).trim();
  expect(inviteCode.length).toBeGreaterThan(0);

  // 2) 학생 — InviteCode로 들어와 제출한다. 본인확인이 없다(ADR-0029) — 로그인만
  // 하고 바로 제출할 수 있어야 한다.
  await establishDeveloperSession(page, studentSeed);
  await page.goto(`/assignments/${inviteCode}`);
  await expect(page.getByTestId("assignment-invite-title")).toHaveText(title);
  // 제출 전 고지 둘 — 소스 열람 가능성과 저작권 귀속(스펙 #197 인수조건).
  await expect(page.getByTestId("assignment-source-reading-notice")).toBeVisible();
  await expect(page.getByTestId("assignment-copyright-notice")).toBeVisible();

  await page.getByTestId("assignment-source-asset-0-upload-input").setInputFiles({
    name: "app.py",
    mimeType: "text/plain",
    buffer: Buffer.from("print('e2e assignment flow')\n", "utf-8"),
  });
  await expect(page.getByTestId("assignment-source-asset-0-value")).toBeVisible({ timeout: 10_000 });

  await page.getByTestId("assignment-submit-button").click();
  await expect(page.getByTestId("assignment-submit-success")).toBeVisible({ timeout: 10_000 });

  // 3) 마감을 실제로 기다린 뒤, celery가 없는 이 잡에서 스캔을 직접 쏜다.
  const remainingMs = deadlineAt.getTime() - Date.now();
  if (remainingMs > 0) {
    await page.waitForTimeout(remainingMs + 2_000);
  }
  await runInternalScan("assignment-close");
  await runInternalScan("submission-scoring");

  // 4) 학생 — 마감 후 자기 Score와 판정 근거를 본다. 요구사항을 하나도 걸지
  // 않았으므로(Assignment 3 시점 폼의 알려진 범위 — 요구사항 없는 과제는
  // "미달"이 성립할 여지가 없어 100.00%로 채점된다, scoring/services.py
  // `_percentage`) 값이 결정적이다.
  await page.reload();
  await expect(page.getByTestId("assignment-score-section")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("assignment-score-percentage")).toHaveText("100.00%");
  // 과제에는 이의제기가 없다 — 학생 화면이 그것을 말한다(스펙 #197 인수조건).
  await expect(page.getByTestId("assignment-no-appeal-notice")).toBeVisible();

  // 5) 강사 — 제출 목록에서 같은 학생·같은 Score를 본다.
  await establishDeveloperSession(page, sponsorSeed);
  await page.goto(assignmentDetailUrl);
  await expect(page.getByTestId("assignment-submission-score-percentage")).toContainText("100.00%", {
    timeout: 15_000,
  });
});
