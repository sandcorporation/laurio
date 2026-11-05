// Sponsor 지표 화면 (#107·#108, 부모 #105) — 「참가작을 하나씩 열어보는 것뿐」이던
// Sponsor 가 자기 Contest 의 참가 추이·Requirement 충족 분포·제출 완성도 분포를
// 본다.
//
// 값 자체(일자별 누적 참가작 수·충족 분포·완성도 분포가 실제 Submission 수와
// 일치하는지, 0 과 「없음」이 다른 층에서 결정되는지, 소유권 경계, Score·developer
// 식별자가 응답 어디에도 없는지)는 backend/tests/test_contest_metrics.py 가 실물로
// 검증한다 — 여기서 확인할 것은 화면이 콘솔에서 클릭으로 닿고, 백엔드가 준 값을
// 그대로 보여주는가다(ADR-0017/0021).
import { expect, test } from "@playwright/test";

import { seedE2eContests } from "./lib/seed";
import { establishDeveloperSession } from "./lib/session";

async function login(page: import("@playwright/test").Page, seed: string): Promise<void> {
  await establishDeveloperSession(page, seed);
}

test("남의 Contest 지표로는 닿을 수 없다 — 있는지가 아니라 없는지를 본다", async ({ page }) => {
  const seeded = await seedE2eContests();
  // judging Contest 의 Sponsor 로 로그인해, 자기 것이 아닌 funded Contest 의
  // 지표를 직접 URL 로 열어본다 — 기존 심사 비교 화면과 같은 소유권 검사를
  // 그대로 쓰므로 403 이어야 한다.
  await login(page, seeded.judging.sponsor_login_seed);

  await page.goto(`/console/contests/${seeded.funded.id}/metrics`);

  await expect(page.getByTestId("metrics-forbidden")).toBeVisible();
  await expect(page.getByTestId("metrics-total-submission-count")).toHaveCount(0);
  await expect(page.getByTestId("metrics-participation-trend")).toHaveCount(0);
});

test("지표 화면 어디에도 Score 도 개별 참가자 신원도 없다 — 있는지가 아니라 없는지를 본다", async ({
  page,
}) => {
  const seeded = await seedE2eContests();
  await login(page, seeded.judging.sponsor_login_seed);

  await page.goto(`/console/contests/${seeded.judging.id}/metrics`);
  await expect(page.getByTestId("metrics-completion-distribution")).toBeVisible();

  const body = await page.content();
  // Score 는 이 화면 어디에도 없다(ADR-0006/0014) — 시드가 실제로 Score 를
  // 만들어 두므로(judging_required_req 채점), "코드 경로가 아예 없어서"가
  // 아니라 "있는데도 안 새는지"를 증명한다.
  expect(body).not.toContain(seeded.judging.sensitive_score_model_version);
  // 개별 Submission·Developer 를 새로 노출하지 않는다 — 심사 비교 화면과 달리
  // 이 화면에는 developer_display_name 자체가 없다.
  expect(body).not.toContain(seeded.judging.sensitive_test_account);
  expect(body).not.toContain(seeded.judging.sensitive_source_object_key_a);
  expect(body).not.toContain(seeded.judging.sensitive_source_object_key_b);
});

// #881 — 내 공모전 목록의 「수정하기」는 백엔드의 `can_edit` 만 따른다. 마감된 행에는 없고
// 지표 보기는 그대로 있다(보이는 쪽은 backend/tests/test_my_contests.py 가 상태별로 못 박는다).
test("마감된 공모전 행에는 수정하기가 없다 — 있는지가 아니라 없는지를 본다", async ({ page }) => {
  const seeded = await seedE2eContests();
  await login(page, seeded.judging.sponsor_login_seed);

  await page.goto("/console/contests");

  const id = seeded.judging.id;
  await expect(page.getByTestId(`my-contest-row-${id}-metrics`)).toBeVisible();
  await expect(page.getByTestId(`my-contest-row-${id}-edit`)).toHaveCount(0);
});
