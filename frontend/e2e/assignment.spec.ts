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
// 않는다. `runInternalScan`으로 `assignment-close`·`submission-scoring`을 직접 쏜다.
//
// **마감을 실제 시간으로 기다리지 않는다(#242).** 예전에는 마감을 45초 뒤로 잡고
// 학생 제출까지 마친 뒤 그 시각을 실제로 `waitForTimeout`으로 흘려보냈다 —
// `test.setTimeout(150_000)` 예산의 3분의 1이 순수 벽시계 대기였고, CI(러너 하나에서
// e2e 잡 셋이 프로덕션 빌드를 상대로 도는 환경)의 얇은 여유 안에서 남은 100여 초에
// 로그인 둘·과제 생성·열기·InviteCode·학생 로그인·이동·업로드·제출·스캔·점수 확인이
// 전부 들어가야 했다. 예산이 다하면 그 순간 진행 중이던 호출이 보고됐다(관측된
// 자리는 우연히 매번 `setInputFiles`) — CI 네 번, 매번 재시도로만 통과해 `1 flaky`로
// 가려졌다.
//
// CLAUDE.md("tick은 시간을 앞당기지 않는다 … 데이터의 시각을 과거로 옮긴다")와 같은
// 이유로, 이제 마감은 넉넉한 미래로 잡아 두고(브라우저 조작이 며칠 걸릴 리 없으므로
// 그 사이 마감이 지날 걱정이 없다) **학생의 제출이 끝난 뒤** `assignment-expire-deadline`
// 시드로 이 과제 하나의 `deadline_at`만 과거로 직접 옮긴다
// (`seed_e2e_expire_assignment_deadline.py`).
//
// **`ClockOverride`(#3, ADR-0003)를 쓰지 않는 이유는 그것이 프로세스 전역 단일
// 행이기 때문이다** — 이 e2e 잡은 워커 여럿이 같은 백엔드에 병렬로 다른 스펙을
// 치므로(`playwright.config.ts`의 `fullyParallel`), 시계를 통째로 미래로 밀면 그
// 순간 도는 다른 스펙의 시간 감각까지 함께 틀어진다(`seed_e2e_operator_queues.py`가
// 이미 겪은 사고와 같은 모양 — 전역 스캔 반경을 건드려 DB의 Contest를 전부
// 전이시킨 적이 있다). 이 과제 하나의 `deadline_at`만 UPDATE하면 그 반경이 이
// 행으로 좁혀진다.
//
// **공개 `PATCH`(`update_assignment`)로 옮기지 않는 이유는 #209 때문이다** — 첫
// 제출이 과제 내용(마감 포함)을 잠가 그 엔드포인트가 409로 거부한다. 그래서
// 관리 명령이 ORM으로 직접 쓰는 시드를 쓴다 — 다른 `seed_e2e_*` 명령들도 이미
// 같은 일을 한다(공개 API의 잠금·검증을 거치지 않고 데이터를 직접 조립한다).

function toDatetimeLocalInput(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

test("강사가 과제를 열어 InviteCode를 주고, 학생이 제출하고, 마감 후 점수를 본다", async ({
  page,
}) => {
  // 기본 테스트 타임아웃(30초)은 로그인 둘·폼 채우기 둘·업로드 하나·스캔
  // 둘까지 CI(프로덕션 빌드, 러너 하나에 e2e 잡 셋이 겹치는 환경)에서 못
  // 견딜 수 있다 — 여유를 준다. **더 이상 실제 시간 대기가 없으므로**(#242)
  // 이 값은 순수하게 네트워크·렌더링 여유일 뿐, 예산의 일부를 미리 깎아
  // 먹는 고정 비용이 아니다.
  test.setTimeout(60_000);

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

  // 마감을 넉넉한 미래로 잡는다 — 아래 브라우저 조작(로그인 둘·폼 채우기
  // 둘·업로드 하나·제출) 전부가 이 시각 이전에 끝나야 제출이 막히지 않는다
  // (`_reject_if_past_deadline`). 더 이상 "그 시각까지 실제로 기다렸다가
  // 지나게 하는" 쪽이 아니라 "제출이 끝난 뒤 이 값을 직접 과거로 옮기는"
  // 쪽이므로(#242, 아래 3번), CI가 아무리 느려도 제출이 이 마감보다 먼저
  // 끝나기만 하면 된다 — 45초처럼 총 예산과 맞물린 값을 고를 이유가 없다.
  const deadlineAt = new Date(Date.now() + 10 * 60_000);

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
  const assignmentId = Number(assignmentDetailUrl.match(/\/assignments\/(\d+)$/)?.[1]);
  expect(Number.isInteger(assignmentId)).toBe(true);

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

  // 3) 제출이 끝난 뒤에야 마감을 과거로 옮긴다(#242) — 순서가 중요하다: 먼저
  // 옮기면 #209(첫 제출이 과제 내용을 잠근다)가 성립하기 전이라 지금은 통과할
  // 것처럼 보여도, 이 스펙이 검증해야 하는 흐름("학생이 마감 전에 제출한다")과
  // 어긋난다. 실제 시간이 지나가길 기다리지 않고 이 과제 하나의 `deadline_at`만
  // 직접 UPDATE한다(`seed_e2e_expire_assignment_deadline.py`) — 시계
  // (`ClockOverride`)는 건드리지 않으므로 같은 잡에서 병렬로 도는 다른 스펙에
  // 영향이 없다.
  await runSeed("assignment-expire-deadline", { assignment_id: assignmentId });
  // celery가 없는 이 잡에서(#40) 전이·채점 스캔을 직접 쏜다.
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
