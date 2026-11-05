import { expect, test } from "@playwright/test";

import { seedE2eContests, type SeededContests } from "./lib/seed";
import { establishDeveloperSession } from "./lib/session";

// 심사 비교 화면 — Requirement 축 매트릭스 + Award (FE-11, #36, ADR-0006, ADR-0014).
//
// 이 스펙이 지키는 두 가지 절대 규칙 — 둘 다 "보여주지 않는다"다:
//
//   1. 소스코드는 이 화면 어디에도 없다 — 선정 전이기 때문이다(ADR-0014). 대신
//      "선정하면 소스가 열린다"는 것을 누르기 전에 알 수 있어야 한다.
//   2. AI 채점 점수는 이 화면 어디에도 없다(ADR-0006) — 선정은 Sponsor의 판단이고
//      Score는 무응답 배분 대상을 가릴 때만 쓰인다.
//
// developer-profile.spec.ts(FE-06, #31)와 같은 기법을 그대로 확장한다 — 시드에
// sentinel 값을 심고, raw 로 받은 HTML/DOM 원문에서 `not.toContain`으로 부재를
// 단언한다. innerText는 보이는 텍스트만 골라내므로 쓰지 않는다 — `page.content()`
// (JS가 렌더한 전체 DOM 직렬화, 화면에 안 보이는 attribute·script까지 포함)와
// `page.request`(로그인 쿠키를 공유하는 raw HTTP, 하이드레이션 전 최초 응답)를
// 둘 다 확인한다.
//
// Award는 Contest 상태를 AWARDED로 영구히 바꾸는 부수효과가 있어(핸드오버까지
// 함께 만들어진다, awards.api) 같은 seed 를 읽는 다른 테스트보다 반드시 나중에
// 실행돼야 한다 — `mode: "serial"`로 선언 순서를 강제한다(workers: 1 이라 원래도
// 순차 실행되지만, 의도를 코드로 명시해 나중에 설정이 바뀌어도 깨지지 않게 한다).
test.describe.configure({ mode: "serial" });

let seeded: SeededContests;

test.beforeAll(async () => {
  seeded = await seedE2eContests();
});

async function loginAsJudgingSponsor(page: import("@playwright/test").Page): Promise<void> {
  await establishDeveloperSession(page, seeded.judging.sponsor_login_seed);
}

async function loginAsOtherSponsor(
  page: import("@playwright/test").Page,
  runId: string,
): Promise<void> {
  await establishDeveloperSession(page, `other-sponsor-${runId}`);
}

test("소스코드와 AI 채점 점수가 HTML 응답 본문 어디에도 없다", async ({ page }) => {
  await loginAsJudgingSponsor(page);

  const url = `/console/contests/${seeded.judging.id}/judge`;

  // 하이드레이션 전 최초 응답(로그인 쿠키를 그대로 공유하는 raw HTTP) — 이
  // 화면은 인증 구역이라 서버 컴포넌트를 쓰지 않으므로(ADR-0015) 원래도 비어
  // 있어야 하지만, 그 사실 자체를 회귀 방지선으로 고정한다.
  const rawRes = await page.request.get(url);
  const rawHtml = await rawRes.text();
  expect(rawHtml).not.toContain(seeded.judging.sensitive_source_object_key_a);
  expect(rawHtml).not.toContain(seeded.judging.sensitive_source_object_key_b);
  expect(rawHtml).not.toContain(seeded.judging.sensitive_test_account);
  expect(rawHtml).not.toContain(seeded.judging.sensitive_score_model_version);

  // 렌더링이 끝난 뒤 — page.content()는 실제로 그려진 DOM 전체를 직렬화한다
  // (화면에 안 보이는 attribute·script 태그까지 포함). innerText만 확인하면
  // "화면에 안 그렸다"만 증명될 뿐 "응답 어디에도 없다"는 증명되지 않는다.
  await page.goto(url);
  await expect(page.getByTestId("comparison-matrix")).toBeVisible();
  const renderedHtml = await page.content();
  expect(renderedHtml).not.toContain(seeded.judging.sensitive_source_object_key_a);
  expect(renderedHtml).not.toContain(seeded.judging.sensitive_source_object_key_b);
  expect(renderedHtml).not.toContain(seeded.judging.sensitive_test_account);
  expect(renderedHtml).not.toContain(seeded.judging.sensitive_score_model_version);

  // 선정하면 소스가 열린다는 것은 누르기 전부터 안내된다 — "감춘다"와 "예고한다"
  // 가 둘 다 인수조건이므로 부재 검증과 같은 테스트에서 함께 확인한다.
  await expect(
    page.getByTestId(`award-source-notice-${seeded.judging.submissions[0].id}`),
  ).toBeVisible();
});

// #165 — 공개 개발자 프로필(/developers/{id})로 가는 링크가 실제로 클릭 가능한지.
// developer-profile.spec.ts 는 `request.get("/developers/{id}")`로 URL을 직접
// 쳐서 SSR만 증명한다 — "사람이 거기 도달할 수 있는가"는 검증하지 않는다(#165
// 본문이 지적한 바로 그 맹점). 이 테스트는 goto/request.get으로 프로필 URL을
// 건너뛰지 않는다 — 심사 비교 화면에 실제로 있는 링크를 클릭해서 도달한다.
test("개발자 이름을 클릭하면 그 개발자의 공개 프로필이 새 탭에 열린다", async ({ page }) => {
  await loginAsJudgingSponsor(page);

  await page.goto(`/console/contests/${seeded.judging.id}/judge`);
  await expect(page.getByTestId("comparison-matrix")).toBeVisible();

  const submission = seeded.judging.submissions[0];
  const link = page.getByTestId(`submission-${submission.id}-developer-link`);
  await expect(link).toHaveText(submission.developer_display_name);
  await expect(link).toHaveAttribute("href", `/developers/${submission.developer_id}`);

  const [profilePage] = await Promise.all([page.waitForEvent("popup"), link.click()]);
  await profilePage.waitForLoadState();

  expect(profilePage.url()).toContain(`/developers/${submission.developer_id}`);
  await expect(profilePage.getByText(submission.developer_display_name).first()).toBeVisible();
});

// #884 — 완성도 열과 「완성도순」. 시드는 A(먼저 낸 제출)를 40.0, B 를 86.7 로 심는다.
test("「완성도순」을 누르면 완성도가 높은 제출작이 앞 열로 온다", async ({ page }) => {
  await loginAsJudgingSponsor(page);
  await page.goto(`/console/contests/${seeded.judging.id}/judge`);
  await expect(page.getByTestId("comparison-matrix")).toBeVisible();

  const [a, b] = seeded.judging.submissions;
  const headers = page.locator('[data-testid^="submission-header-"]');
  await expect(headers.nth(0)).toHaveAttribute("data-testid", `submission-header-${a.id}`);
  await expect(headers.nth(1)).toHaveAttribute("data-testid", `submission-header-${b.id}`);
  await expect(page.getByTestId(`quality-${a.id}`)).toContainText("40.0");
  await expect(page.getByTestId(`quality-${b.id}`)).toContainText("86.7");
  await expect(page.getByTestId(`quality-${b.id}`)).toContainText("1등");

  await page.getByTestId("judge-sort-quality").click();
  await expect(headers.nth(0)).toHaveAttribute("data-testid", `submission-header-${b.id}`);
  await expect(headers.nth(1)).toHaveAttribute("data-testid", `submission-header-${a.id}`);

  // 항목별 근거가 그 요구사항 칸에 함께 있다.
  const requirementId = seeded.judging.requirements[0].id;
  await expect(page.getByTestId(`quality-item-${requirementId}-${b.id}`)).toContainText("항목 완성도 5/5");
});

// #179 — Award 직후 Sponsor가 「내 차례 · 인수를 확인하세요」를 보고도 갈 곳이
// 없던 자리. Escrow 해제는 돈이 움직이는 곳이라(CLAUDE.md 「남길 것」) 스펙을
// 하나 남긴다 — 새 스펙 파일을 만들지 않고, Award를 실제로 수행하는 이 파일에
// 이어 붙인다(위 serial 주석이 이미 이 자리를 예고하고 있었다). 이 테스트가
// Contest를 AWARDED로 영구히 바꾸므로 파일의 **마지막**에 둔다.
test("Award 뒤 Sponsor가 인수를 확인하면 Escrow가 해제된다", async ({ page }) => {
  await loginAsJudgingSponsor(page);

  const submission = seeded.judging.submissions[0];
  await page.goto(`/console/contests/${seeded.judging.id}/judge`);
  await expect(page.getByTestId("comparison-matrix")).toBeVisible();

  await page.getByTestId(`award-button-${submission.id}`).click();
  await page.getByTestId(`award-confirm-${submission.id}`).click();
  await expect(page.getByTestId("award-success")).toBeVisible();

  // Award 직후 인수 확인 화면으로 간다 — 「내 공모전」의 「인수 확인하러
  // 가기」 링크가 실제로 여기로 보낸다(use-my-contests.ts의
  // canAcceptHandover).
  await page.goto(`/console/contests/${seeded.judging.id}/handover`);
  await expect(page.getByTestId("handover-pending-notice")).toBeVisible();
  // 자동 해제가 있다는 사실을 숨기지 않는다 — 방치해도 상금이 묶이지 않는다.
  await expect(page.getByTestId("handover-deadline-notice")).toBeVisible();

  await page.getByTestId("handover-accept-button").click();
  await expect(page.getByTestId("handover-accept-confirm-notice")).toBeVisible();
  await page.getByTestId("handover-accept-confirm").click();

  await expect(page.getByTestId("handover-released")).toBeVisible();
  await expect(page.getByTestId("handover-accept-button")).toHaveCount(0);
});
