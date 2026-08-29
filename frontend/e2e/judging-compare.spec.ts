import { expect, test } from "@playwright/test";

import { seedE2eContests, type SeededContests } from "./lib/seed";

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

test.beforeAll(() => {
  seeded = seedE2eContests();
});

async function loginAsJudgingSponsor(page: import("@playwright/test").Page): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("fake-login-seed").fill(seeded.judging.sponsor_login_seed);
  await page.getByTestId("login-kakao").click();
  await expect(page).toHaveURL(/\/console/);
}

async function loginAsOtherSponsor(
  page: import("@playwright/test").Page,
  runId: string,
): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("fake-login-seed").fill(`other-sponsor-${runId}`);
  await page.getByTestId("login-kakao").click();
  await expect(page).toHaveURL(/\/console/);
}

test("필수·선택 Requirement가 구분되고, 증거 없는 칸이 즉시 구분된다", async ({ page }) => {
  await loginAsJudgingSponsor(page);
  await page.goto(`/console/contests/${seeded.judging.id}/judge`);
  await expect(page.getByTestId("comparison-matrix")).toBeVisible();

  const [requiredReq, optionalReq] = seeded.judging.requirements;
  const [submissionA, submissionB] = seeded.judging.submissions;

  // 필수/선택 배지가 각 행에 붙는다.
  await expect(page.getByTestId(`requirement-${requiredReq.id}-grade`)).toHaveText("필수");
  await expect(page.getByTestId(`requirement-${optionalReq.id}-grade`)).toHaveText("선택");

  // 심사 마감까지 남은 기간과, 방치했을 때 벌어지는 일(1/N 자동 배분)이 보인다.
  await expect(page.getByTestId("judging-deadline")).toContainText("D-");
  await expect(page.getByTestId("judging-consequence-notice")).toContainText("1/N");

  // Submission A는 필수 Requirement에 증거를 연결했다 — 즉시 "충족"으로 구분되고
  // 증거 위치(소스 내 포인터, 소스 내용 자체가 아니다)가 보인다.
  const cellARequired = page.getByTestId(`cell-${requiredReq.id}-${submissionA.id}`);
  await expect(cellARequired).toHaveAttribute("data-linked", "true");
  await expect(cellARequired).toContainText("충족");
  await expect(cellARequired).toContainText("src/auth/login.ts");
  await expect(page.getByTestId(`cell-${requiredReq.id}-${submissionA.id}-empty`)).toHaveCount(0);

  // Submission A는 선택 Requirement에는 자가 응답만 있고 증거가 없다 — 증거 없는
  // 칸으로 구분되지만, 선택 항목이라 "미달로 채점됩니다" 경고는 붙지 않는다.
  const cellAOptional = page.getByTestId(`cell-${optionalReq.id}-${submissionA.id}-empty`);
  await expect(cellAOptional).toBeVisible();
  await expect(cellAOptional).not.toContainText("미달");

  // Submission B는 두 Requirement 모두 자가 응답 자체가 없다 — 필수 쪽은 "증거
  // 없음"과 함께 미달 경고까지 붙어 즉시 구분된다.
  const cellBRequired = page.getByTestId(`cell-${requiredReq.id}-${submissionB.id}-empty`);
  await expect(cellBRequired).toBeVisible();
  await expect(cellBRequired).toContainText("미달");
  const cellBOptional = page.getByTestId(`cell-${optionalReq.id}-${submissionB.id}-empty`);
  await expect(cellBOptional).toBeVisible();
});

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

test("다른 Sponsor는 이 Contest를 비교할 수도, Award할 수도 없다", async ({ page }) => {
  const runId = `${Date.now()}`;
  await loginAsOtherSponsor(page, runId);

  // 비교 화면 자체가 403으로 거부된다.
  await page.goto(`/console/contests/${seeded.judging.id}/judge`);
  await expect(page.getByTestId("compare-forbidden")).toBeVisible();
  await expect(page.getByTestId("comparison-matrix")).toHaveCount(0);

  // UI가 먼저 막더라도, 백엔드가 실제로 거부하는지와 프론트가 그 거부를 제대로
  // 드러내는지를 네트워크 레벨에서도 직접 증명한다 — 다른 사람은 Award할 수
  // 없다는 것이 이 티켓의 핵심 인수조건이다.
  const submissionId = seeded.judging.submissions[0].id;
  const result = await page.evaluate(
    async ({ contestId, submissionId: sid }) => {
      const res = await fetch(`/api/backend/contests/${contestId}/award`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ submission_id: sid }),
      });
      return { status: res.status, body: await res.json().catch(() => null) };
    },
    { contestId: seeded.judging.id, submissionId },
  );
  expect(result.status).toBe(403);
});

test("Sponsor 본인은 하나의 Submission을 Award할 수 있다", async ({ page }) => {
  await loginAsJudgingSponsor(page);
  await page.goto(`/console/contests/${seeded.judging.id}/judge`);
  await expect(page.getByTestId("comparison-matrix")).toBeVisible();

  const [submissionA, submissionB] = seeded.judging.submissions;

  await page.getByTestId(`award-button-${submissionA.id}`).click();
  await expect(page.getByTestId(`award-confirm-notice-${submissionA.id}`)).toBeVisible();
  await page.getByTestId(`award-confirm-${submissionA.id}`).click();

  await expect(page.getByTestId("award-success")).toContainText(String(submissionA.id));
  await expect(page.getByTestId(`awarded-badge-${submissionA.id}`)).toBeVisible();

  // 이미 Award된 뒤에는 다른(또는 같은) Submission을 다시 Award할 수 없다 — 버튼
  // 자체가 사라진다.
  await expect(page.getByTestId(`award-button-${submissionB.id}`)).toHaveCount(0);
  await expect(page.getByTestId(`award-button-${submissionA.id}`)).toHaveCount(0);
});
