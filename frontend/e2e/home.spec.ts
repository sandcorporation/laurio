// LP-01 (#93, spec #92) — 사이트에 입구를 낸다.
//
// 이 파일이 세우는 것은 헤더 자체가 아니라 **닿을 수 있음**이다. 티켓의 이유가
// 된 실패는 "119건이 초록인데 입구가 없다"였다 — 모든 기존 e2e가
// `page.goto()`로 URL을 직접 쳤기 때문에 아무도 "첫 방문자가 / 에서 클릭만으로
// 어디까지 갈 수 있는가"를 보지 않았다. 아래 마지막 테스트가 그 구멍을 메운다.
//
// 코드리뷰 지적(#93 1차) — 처음 버전의 걷기 테스트는 헤더 링크 셋만 돌아
// 홈의 <section> 을 통째로 지우고 행 링크를 망가뜨려도 초록이었다. 「입구가
// 있다」를 증명해야 하는데 「헤더에 링크가 있다」만 증명한 것이다. 아래에서는
// 실제 시드 Contest 행을 클릭해 그 Contest 의 상세까지 닿는다.
import fs from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { seedE2eContests, type SeededContests } from "./lib/seed";

let seeded: SeededContests;

test.beforeAll(async () => {
  seeded = await seedE2eContests();
});

test.describe("@exclusive 헤더 — 모든 페이지에 같은 모양으로 선다", () => {
  for (const target of ["/", "/contests", "/login"]) {
    test(`${target} 에도 브랜드·공모전·개최 CTA 가 있다`, async ({ page }) => {
      await page.goto(target);
      await expect(page.getByTestId("header-brand")).toBeVisible();
      await expect(page.getByTestId("header-nav-contests")).toBeVisible();
      await expect(page.getByTestId("header-cta-new-contest")).toBeVisible();
    });
  }

});

test.describe("@exclusive 홈 — 자리표시가 아니라 실제 공모전을 보여준다", () => {
  test('이 페이지에 "use client" 가 없다', () => {
    // ADR-0015 — 홈은 공개 표면이라 서버 컴포넌트로 남아야 색인된다.
    const source = fs.readFileSync(path.join(__dirname, "../app/page.tsx"), "utf-8");
    expect(source).not.toContain('"use client"');
  });

  test.describe("자바스크립트 없이", () => {
    test.use({ javaScriptEnabled: false });

    test("공개 공모전이 서버 렌더링된 HTML 에 들어 있다", async ({ page }) => {
      await page.goto("/");
      const html = await page.content();
      expect(html).toContain(seeded.funded.title);
    });

    // 코드리뷰 지적(#93 1차) — 홈 본문만 보던 자바스크립트-없음 테스트는
    // 헤더가 하이드레이션 뒤로 밀리는 회귀(ADR-0015 가 막으려는 바로 그
    // 실패)를 못 잡는다. 헤더도 서버에서 렌더된다는 것을 여기서 직접 본다.
    test("헤더 링크도 자바스크립트 없이 그대로 보인다", async ({ page }) => {
      await page.goto("/");
      await expect(page.getByTestId("header-brand")).toBeVisible();
      await expect(page.getByTestId("header-nav-contests")).toBeVisible();
      await expect(page.getByTestId("header-cta-new-contest")).toBeVisible();
    });
  });

  // 코드리뷰 지적(#93 1차) — 행의 href·data-contest-row 를 직접 검증하는
  // 테스트가 없어서 오타를 내도 스위트가 초록이었다. 아래에서 특정 행을 눌러
  // 정확히 그 Contest 의 상세로 이어지는지 본다.
  // 코드리뷰 지적(#93 2차) — /contests 는 「상금미달」 배지와 "참가를 막지
  // 않습니다" 각주를 낸다. 홈이 액센트 색으로만 이 상태를 표시하면, 그
  // 규칙을 가장 모를 첫 방문자가 보는 화면에서만 그 규칙이 사라진다.
});

// LP-02 (#94, spec #92) — 홈이 공모전을 네 묶음으로 큐레이션한다.
//
// **묶음 판정은 백엔드가 한다**(GET /api/contests/home,
// contests.curation.home_bucket_for) — 아래 테스트는 그 판정이 화면에 그대로
// 나타나는지, 그리고 어떤 묶음이 비어도 섹션째 사라지지 않는지를 클릭·텍스트로
// 확인한다. 백엔드 쪽 "모든 Contest.Status가 어떤 묶음엔가 들어간다"는 고정은
// backend/tests/test_home_curation.py 의 몫이다 — 여기서는 화면이 그 결과를
// 정직하게 옮기는지만 본다.
test.describe("@exclusive 홈 — 공모전을 네 묶음으로 큐레이션한다", () => {
  // seed_e2e_contests.py: funded 는 deadline_at = now+10일(PUBLISHED) — 마감임박
  // 임계값(3일, contests.curation.HOME_IMMINENT_DEADLINE_DAYS)보다 멀다.
  // seed_e2e_contests.py: underfunded 는 deadline_at = now+2일(PUBLISHED) — 임계값
  // 이내다. 「마감이 가까운 Contest가 진행중이 아니라 마감임박에 들어간다」는
  // #94 인수조건을 직접 확인한다.
  // seed_e2e_contests.py: closed 는 CLOSED다 — 마감됐고 심사기간 중(ADR-0014,
  // 데모·영상은 이미 전면 공개).
  // 기본 시드에는 AWARDED·JUDGING_ENDED Contest 가 없다 — 「완료」가 실제로 빈
  // 채로 렌더되는 경우를 이 사실이 그대로 제공한다. 섹션이 사라지거나 깨지지
  // 않고 "비어 있다"고 말해야 한다(#94 인수조건).
  // 각 묶음에서 공모전 목록으로 이어질 수 있어야 한다(#94 인수조건) — 홈은
  // 큐레이션이고 목록(필터·정렬·페이지네이션, #39)은 탐색이라 그 둘을 잇는
  // 통로가 있어야 한다.
});

// PS-01 (#106, spec #105) — 참가작 수가 홈 카드에서 시작해 목록·상세까지
// 같은 값으로 따라온다. **묶음 판정과 마찬가지로 참가작 수도 백엔드가 낸다**
// (GET /api/contests/home 의 ContestOut.submission_count) — 화면은 그 숫자를
// 문구로 옮길 뿐 다시 세지 않는다. seed_e2e_contests.py 의 funded 는
// Submission 을 하나 심으므로(developer 픽스처), seeded.funded.submission_count
// 로 기대값을 하드코딩하지 않고 시드가 준 값을 그대로 쓴다.
test.describe("@exclusive 홈 — 참가작 수가 화면을 옮겨도 같은 값을 유지한다", () => {
  // 0도 숨기지 않는다 — "0" 이라는 숫자가 아니라 "아직 참가작이 없습니다"로
  // 읽힌다(#106 인수조건). seed_e2e_contests.py 의 underfunded 는 Submission 이
  // 없다.
});

// 이 스펙의 존재 이유. 티켓 #93 본문 그대로: 이 테스트가 있었다면 입구 없는
// staging 이 나가지 않았다. `page.goto`는 맨 처음 한 번뿐이고, 그 뒤로는 전부
// 클릭이다.
//
// 코드리뷰 지적(#93 1차)을 반영해, 헤더 링크뿐 아니라 홈에 실제로 렌더된
// Contest 행을 먼저 클릭해 그 상세에 닿는 것부터 확인한다 — 홈의 <section>
// 이 통째로 사라지거나 행 링크가 깨지면 이 자리에서 실패해야 한다.
test("@exclusive 첫 방문자가 / 에서 시작해 클릭만으로 실제 공모전과 공모전 목록·로그인 화면에 닿는다", async ({
  page,
}) => {
  await page.goto("/");

  // 실제 공모전 상세 — 홈이 렌더한 행을 직접 누른다.
  await page.locator(`[data-contest-row="${seeded.funded.id}"]`).click();
  await expect(
    page.getByRole("heading", { level: 1, name: seeded.funded.title }),
  ).toBeVisible();

  // 헤더는 상세 페이지에도 서 있다 — 브랜드를 눌러 홈으로. 이것도 클릭이다,
  // URL 을 다시 치지 않는다.
  await page.getByTestId("header-brand").click();
  // 코드리뷰 지적(#93 1차) — `/\/$/` 는 "/contests/" 처럼 슬래시로 끝나는
  // 어떤 경로도 통과시킨다. 정확히 루트인지 문자열로 단언한다.
  await expect(page).toHaveURL("/");

  // 공모전 목록.
  await page.getByTestId("header-nav-contests").click();
  await expect(page).toHaveURL(/\/contests$/);
  await expect(page.getByTestId("contest-count")).toBeVisible();

  await page.getByTestId("header-brand").click();
  await expect(page).toHaveURL("/");

  // 로그인 화면.
  await expect(page.getByTestId("header-login-link")).toBeVisible();
  await page.getByTestId("header-login-link").click();
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByTestId("login-kakao")).toBeVisible();
});
