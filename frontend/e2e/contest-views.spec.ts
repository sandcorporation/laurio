// ContestView — 조회수와 전환율 (#109, 부모 #105, `CONTEXT.md`의 `ContestView`).
//
// 중복 제거·날짜 경계·Sponsor 자기 조회 배제·방문자 식별값 부재는
// backend/tests/test_contest_metrics.py 가 실물로 검증한다(시임은 HTTP다,
// CLAUDE.md). 여기서 확인할 것은 두 앱을 가로지르는 실제 왕복이다: 브라우저가
// 공개 상세를 열면 백엔드가 조회를 세고, 그 수가 Sponsor 지표 화면에
// 조회수·전환율로 나타나는가 — 그리고 그 신호가 정말 "브라우저가 마운트된
// 뒤"에만 나가는가(JS 를 끈 방문자는 세지 않는다, ADR-0015 와 같은 자리의
// side-effect-free 렌더).
import { expect, test } from "@playwright/test";

import { seedE2eContests } from "./lib/seed";
import { establishDeveloperSession } from "./lib/session";

async function login(page: import("@playwright/test").Page, seed: string): Promise<void> {
  await establishDeveloperSession(page, seed);
}

test("JS 를 끈 방문자는 세지 않는다 — 서버 렌더만으로는 조회가 늘지 않는다", async ({
  browser,
}) => {
  const seeded = await seedE2eContests();

  const noJsContext = await browser.newContext({ javaScriptEnabled: false });
  const noJsPage = await noJsContext.newPage();
  const response = await noJsPage.goto(`/contests/${seeded.judging.id}`);
  expect(response?.status()).toBeLessThan(400);
  await noJsContext.close();

  const sponsorContext = await browser.newContext();
  const sponsorPage = await sponsorContext.newPage();
  await login(sponsorPage, seeded.judging.sponsor_login_seed);
  await sponsorPage.goto(`/console/contests/${seeded.judging.id}/metrics`);

  await expect(sponsorPage.getByTestId("metrics-view-count")).toHaveText("0");
  await sponsorContext.close();
});
