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
