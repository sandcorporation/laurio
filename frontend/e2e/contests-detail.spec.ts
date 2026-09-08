import fs from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { seedE2eContests, type SeededContests } from "./lib/seed";

// FE-05(#30) — `/contests/{id}` 가 서버에서 렌더링되는지 증명한다. 이 페이지에는
// 클라이언트 상호작용이 없으므로(정적 상세 화면) raw `request` 로 받은 HTML을
// 그대로 확인한다 — ADR-0017: 브라우저가 필요 없는 것은 `request` 로, 같은 시임.
// 클라이언트에서 값을 가져왔다면 이 HTML에는 애초에 없을 것이므로, 이 자체가
// SSR 증명이다(frontend/e2e/seam.spec.ts 상단 주석).
let seeded: SeededContests;

test.beforeAll(async () => {
  seeded = await seedE2eContests();
});

// **지시어는 파일 맨 앞에 있을 때만 지시어다.** 예전에는 파일 전체에서 그 문자열을
// 찾았는데, #234 가 이미지 섹션에 「이 파일에는 `"use client"` 가 없다」고 설명하는
// 주석을 달자 그 주석에 걸려 CI 가 빨개졌다 — 페이지는 멀쩡한 서버 컴포넌트인데도.
// 주석과 문자열 리터럴을 걷어내고 **첫 실행 문장**만 본다. 진짜 회귀(맨 위에 지시어가
// 붙는 것)는 그대로 잡히고, 그것을 설명하는 글은 잡히지 않는다.
test("@exclusive 이 페이지에 \"use client\" 가 없다", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "../app/contests/[id]/page.tsx"),
    "utf-8",
  );
  const withoutComments = source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
  const firstStatement = withoutComments.split("\n").map((l) => l.trim()).find(Boolean);
  expect(firstStatement).not.toMatch(/^["']use client["']/);
});

test("@exclusive 요구사항과 Requirement 체크리스트가 서버 렌더링된 HTML 에 들어 있다", async ({ request }) => {
  const res = await request.get(`/contests/${seeded.funded.id}`);
  expect(res.status()).toBe(200);
  const html = await res.text();

  expect(html).toContain(seeded.funded.title);
  expect(html).toContain(seeded.funded.prize.toLocaleString("ko-KR"));
  for (const requirement of seeded.funded.requirements) {
    expect(html).toContain(requirement.text);
  }
});

// PS-01 (#106, spec #105) — 참가작 수가 상세에도 보이고, 백엔드가 낸 값과
// 일치한다. seed_e2e_contests.py 가 실제로 심은 뒤 다시 세어 돌려준 값
// (seeded.funded.submission_count)을 그대로 기대값으로 쓴다 — 화면은 다시
// 세지 않는다.
// 0도 숨기지 않는다 — "0"이라는 숫자가 아니라 "아직 참가작이 없습니다"로
// 읽힌다. 숫자와 문구가 다른 층에서 결정된다는 것이 #106 인수조건이다.
test("@exclusive draft Contest 는 404 이고, 존재 여부를 드러내지 않는다", async ({ request }) => {
  const draftRes = await request.get(`/contests/${seeded.draft.id}`);
  const missingRes = await request.get("/contests/999999999");

  expect(draftRes.status()).toBe(404);
  const draftHtml = await draftRes.text();
  const missingHtml = await missingRes.text();

  // draft 의 제목이 404 응답 어디에도 새어나오지 않는다.
  expect(draftHtml).not.toContain(seeded.draft.title);
  // 존재하지 않는 것과 draft 인 것이 같은 모양의 404 로 응답한다 — 상태값으로
  // "있는데 숨겼다"를 구분할 수 없어야 한다.
  expect(draftRes.status()).toBe(missingRes.status());
});
