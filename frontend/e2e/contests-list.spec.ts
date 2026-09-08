import fs from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { seedE2eContests, type SeededContests } from "./lib/seed";

// FE-04(#29) — `/contests` 가 서버에서 렌더링되는지 증명한다.
//
// frontend/e2e/seam.spec.ts 상단 주석이 세운 규율 그대로: HTML 에 마크업이 있다는
// 것만으로는 "use client" 실수를 못 잡는다. 실제로 갈리는 것은 **백엔드에서 온
// 값**이다 — 그래서 아래 테스트들은 seed_e2e_contests 가 방금 DB에 심은 제목·
// 상금·마감을, 클라이언트에서 다시 요청하지 않고 받은 JS-off HTML 에서 직접
// 찾는다. 이 시드는 하드코딩 픽스처가 아니라 진짜 Django Contest 다(e2e/lib/seed.ts).
let seeded: SeededContests;

test.beforeAll(async () => {
  seeded = await seedE2eContests();
});

test("@exclusive 이 페이지에 \"use client\" 가 없다", () => {
  // AC를 코드로 직접 확인한다 — HTTP 시임만으로는 서버/클라이언트 컴포넌트
  // 여부를 구분할 수 없으므로(둘 다 초기 요청에 프리렌더된다), 여기서만 예외적으로
  // 소스를 읽는다. 렌더링 결과(백엔드 값이 JS-off HTML 에 있는지)는 아래
  // 테스트들이 별도로 증명한다 — 이 테스트는 그 증명이 우연이 아님을 보강한다.
  const source = fs.readFileSync(
    path.join(__dirname, "../app/contests/page.tsx"),
    "utf-8",
  );
  expect(source).not.toContain('"use client"');
});

test.describe("@exclusive 자바스크립트 없이", () => {
  test.use({ javaScriptEnabled: false });

  test("공모전 제목·상금·마감이 서버 렌더링된 HTML 에 들어 있다", async ({ page }) => {
    await page.goto("/contests");
    const html = await page.content();

    // 백엔드가 준 값 그대로 — 프론트가 흉내 낸 값이 아니다.
    expect(html).toContain(seeded.funded.title);
    expect(html).toContain(seeded.funded.prize.toLocaleString("ko-KR"));

    expect(html).toContain(seeded.underfunded.title);
    expect(html).toContain(seeded.underfunded.prize.toLocaleString("ko-KR"));
  });

  test("draft Contest 는 목록에 나오지 않는다", async ({ page }) => {
    await page.goto("/contests");
    const html = await page.content();
    expect(html).not.toContain(seeded.draft.title);
  });

  // #227 — 기본 목록은 "지금 참가할 수 있는 것"만 보여준다. seed_e2e_contests.py
  // 의 `closed` 는 CLOSED 상태로 심긴다(마감 시각이 과거) — 예전에는 이것도
  // 기본 목록에 나왔지만, 이제는 `?closed=true` 로 명시해야만 나온다. 백엔드가
  // 준 값이 어느 조건에서 나오고 어느 조건에서 안 나오는지를 JS-off HTML 로
  // 직접 본다 — 이 파일의 나머지 테스트들과 같은 시임(risk 1, ADR-0017).
  test("마감된 Contest 는 기본 목록에서 빠지고 closed=true 로만 나온다", async ({ page }) => {
    await page.goto("/contests");
    expect(await page.content()).not.toContain(seeded.closed.title);

    await page.goto("/contests?closed=true");
    const html = await page.content();
    expect(html).toContain(seeded.closed.title);
    expect(html).toContain(seeded.closed.prize.toLocaleString("ko-KR"));
  });

});

// `page.content()` 는 쓰지 않는다 — Next 의 `<Link>` 클릭은 클라이언트 소프트
// 내비게이션이라 문서 전체를 다시 받지 않고, 최초 로드 때 심어진 하이드레이션용
// `<script>` 태그(RSC flight 페이로드)는 클릭 이후에도 DOM 에 그대로 남는다. 그
// 안에는 필터 적용 전 문자열이 문자 그대로 박제돼 있어 `page.content()`(document
// 전체 직렬화)로 보면 필터링이 안 된 것처럼 오검출된다. `main` 안의 실제 렌더링된
// 텍스트만 보면 이 문제가 없다.
// PS-01 (#106, spec #105) — 참가작 수가 목록에 보이고, 백엔드가 낸 값과
// 일치한다(심고 세는 것을 같은 테스트에서 대비시킨다, #106 인수조건). 화면은
// 이 숫자를 다시 세지 않는다 — seed_e2e_contests.py 가 이미 심은 뒤 다시 세어
// 돌려준 값(seeded.funded.submission_count)을 그대로 기대값으로 쓴다.
// 0도 숨기지 않는다 — "0"이라는 숫자가 아니라 "아직 참가작이 없습니다"로
// 읽힌다. 숫자와 문구가 다른 층에서 결정된다는 것이 #106 인수조건이다.