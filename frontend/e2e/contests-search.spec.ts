import { expect, test } from "@playwright/test";

import { seedE2eContests, type SeededContests } from "./lib/seed";

// #452 (부모 #444 스펙) — `/contests?q=…`가 JS 를 끈 HTML 에 검색 결과를 담는다.
//
// **이 파일이 검증하는 대상은 SSR 뿐이다.** 검색 자체(관련도 가중치·조사 변화
// 대응·어댑터 실패 시 DB 폴백 등)는 백엔드가 마운트된 HTTP API 하나로 이미
// 고정한다(`backend/tests/test_contest_search.py`, CLAUDE.md 「HTTP가 유일한
// 시임이다」) — 여기서 다시 단언하지 않는다. `contests-list.spec.ts`(FE-04, #29)
// 와 같은 시임(risk 1, ADR-0017)을 검색 쿼리에 대해서도 지킨다: 백엔드가 준
// 값이 클라이언트에서 다시 요청하지 않고 받은 JS-off HTML 에 그대로 있는가.
//
// **`category`로 검색 범위를 자기 네임스페이스 안으로 좁힌다.** fake 검색
// 어댑터(`contests.search.FakeContestSearchAdapter`)는 DB 전체를 훑는다 —
// 병렬로 도는 다른 워커가 같은 순간에 심어 둔 "[E2E-wN] 알림 앱 리디자인" 같은
// 동명의 Contest 가 섞여 들어올 수 있다(#104의 워커별 네임스페이스는 접두어만
// 가를 뿐 검색 자체를 가르지 않는다). `seeded.funded.category_id`는 이 워커의
// 네임스페이스 전용 Category 라, 그 축으로 좁히면 이 스펙 밖의 Contest 가 섞일
// 수 없다.
let seeded: SeededContests;

test.beforeAll(async () => {
  seeded = await seedE2eContests();
});

test.describe("@exclusive 자바스크립트 없이", () => {
  test.use({ javaScriptEnabled: false });

  test("/contests?q=… 가 검색 결과를 서버 렌더링된 HTML 에 담는다", async ({ page }) => {
    // seed_e2e_contests.py: funded 의 제목은 `{prefix}알림 앱 리디자인`이고
    // underfunded 는 `{prefix}러닝 크루 기록 앱`이다 — "알림"은 전자에만 있다.
    const needle = "알림";
    expect(seeded.funded.title).toContain(needle);
    expect(seeded.underfunded.title).not.toContain(needle);

    await page.goto(`/contests?q=${encodeURIComponent(needle)}&category=${seeded.funded.category_id}`);
    const html = await page.content();

    expect(html).toContain(seeded.funded.title);
    expect(html).not.toContain(seeded.underfunded.title);

    // 검색어가 있으면 정렬 기본값이 관련도순이다(#449) — 도구 막대의 정렬
    // `<select>`가 그 값을 선택된 채로 그린다(#452 인수조건).
    expect(html).toContain("관련도순");

    // 걸린 검색어가 칩으로 보인다(#452 인수조건).
    expect(html).toContain(needle);
  });

  test("검색어와 무관한 카테고리로 좁히면 결과가 없다", async ({ page }) => {
    // 검색어 자체는 일치해도 카테고리 축이 다르면 걸리지 않는다(#39 — 필터는
    // AND로 좁힌다는 규칙이 검색어에도 그대로 적용된다). underfunded 가 속한
    // 카테고리(생산성)로 "알림"을 검색하면 0건이어야 한다.
    await page.goto(
      `/contests?q=${encodeURIComponent("알림")}&category=${seeded.underfunded.category_id}`,
    );
    const html = await page.content();

    expect(html).not.toContain(seeded.funded.title);
    expect(html).toContain("조건에 맞는 공모전이 없습니다");
  });
});
