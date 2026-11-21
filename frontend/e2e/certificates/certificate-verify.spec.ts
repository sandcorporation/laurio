import { expect, test } from "@playwright/test";

// 상장 확인 페이지(#1128) — QR 로만 닿는 곳이라 검색 엔진에 싣지 않는다. 세 상태의 칸
// 규칙은 백엔드 시험(tests/integration/test_certificate_verify.py)과 표시 규칙 시험
// (lib/certificates/verify.test.ts)이 보고, 여기서는 Next 가 내는 것만 본다: 없는 토큰의
// 404, 헤더, robots.txt.
test("없는 토큰은 404 이고 검색 엔진을 막는 헤더가 붙는다", async ({ request }) => {
  const response = await request.get("/c/xxxxxxxxxxxxxxxxxxxxxx");

  expect(response.status()).toBe(404);
  expect(response.headers()["x-robots-tag"]).toBe("noindex, nofollow");
});

test("robots.txt 가 /c/ 를 막는다", async ({ request }) => {
  const body = await (await request.get("/robots.txt")).text();

  expect(body).toMatch(/^Disallow: \/(c\/)?$/m);
});
