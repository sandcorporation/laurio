import fs from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { seedE2eContests, type SeededContests } from "./lib/seed";

// FE-06(#31) — `/developers/{id}` 가 서버에서 렌더링되는지 증명한다.
// `REQUEST.md` 가 약속한 「검색엔진에 색인되는 공개 URL」이 이 페이지다 —
// 탈락한 Developer 가 받는 유일한 보상이 여기 걸려 있다(spec #25).
//
// contests-detail.spec.ts 와 같은 기법이다(ADR-0017, seam.spec.ts 상단 주석) —
// 클라이언트에서 값을 가져왔다면 이 HTML 에는 애초에 없을 것이므로, raw
// `request` 로 받은 HTML 에 **백엔드가 준 값**이 들어 있는지 확인하는 것 자체가
// SSR 증명이다.
let seeded: SeededContests;

test.beforeAll(async () => {
  seeded = await seedE2eContests();
});

test('이 페이지에 "use client" 가 없다', () => {
  const source = fs.readFileSync(path.join(__dirname, "../app/developers/[id]/page.tsx"), "utf-8");
  expect(source).not.toContain('"use client"');
});

test("개발자 프로필과 아카이브된 Submission 목록이 서버 렌더링된 HTML 에 들어 있다", async ({
  request,
}) => {
  const res = await request.get(`/developers/${seeded.developer.id}`);
  expect(res.status()).toBe(200);
  const html = await res.text();

  expect(html).toContain(seeded.developer.display_name);
  expect(html).toContain(seeded.developer.bio);
  expect(html).toContain(seeded.developer.archived_submission.contest_title);
});

test("아직 마감되지 않은 Contest 에 낸 Submission 은 프로필에 나타나지 않는다", async ({
  request,
}) => {
  // seed_e2e_contests 는 같은 developer 로 `funded`(진행 중) Contest 에도
  // Submission 을 하나 심는다 — ADR-0014 아카이브 판정("마감된 Contest 만")이
  // 실제로 걸러내는지 여기서 확인한다.
  const res = await request.get(`/developers/${seeded.developer.id}`);
  const html = await res.text();

  expect(html).not.toContain(seeded.funded.title);
});

// --- 노출 금지 두 가지(ADR-0014, 이 티켓의 가장 위험한 수락 기준) --------------
//
// "화면에 안 그렸다"로는 부족하다 — HTML 응답 본문 전체(SSR 페이로드·Next
// 하이드레이션 스크립트 포함)에 값이 없어야 한다. 그래서 `page.locator(...).
// innerText()` 가 아니라 raw `request` 로 받은 HTML **원문 전체**를 확인한다 —
// innerText 는 보이는 텍스트만 골라내므로 하이드레이션 <script> 안에 값이 남아
// 있어도 통과해버린다.

test("소스코드 object_key 는 HTML 응답 본문 어디에도 없다", async ({ request }) => {
  const res = await request.get(`/developers/${seeded.developer.id}`);
  const html = await res.text();

  expect(html).not.toContain(seeded.developer.sensitive_source_object_key);
});

test("test_account 는 HTML 응답 본문 어디에도 없다", async ({ request }) => {
  const res = await request.get(`/developers/${seeded.developer.id}`);
  const html = await res.text();

  expect(html).not.toContain(seeded.developer.sensitive_test_account);
});
