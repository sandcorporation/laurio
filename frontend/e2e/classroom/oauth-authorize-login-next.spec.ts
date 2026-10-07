import { expect, test } from "@playwright/test";

// 비로그인으로 연 /oauth/authorize 를 로그인으로 보낼 때 `next` 가 요청 원문을
// 보존하는지 — 실제 서버(미들웨어 포함)를 거친다(#622). Next 의 NextURL 은 쿼리 안
// 127.0.0.1 을 localhost 로 바꿔 파싱하므로, 루프백 redirect_uri(Codex)가 로그인 뒤
// 등록값과 달라져 거절됐다. `skipMiddlewareUrlNormalize` 가 켜져 있어야 지켜진다.
test("비로그인 authorize 의 127.0.0.1 redirect_uri 가 로그인 next 에 그대로 남는다", async ({
  request,
}) => {
  const redirectUri = "http://127.0.0.1:56915/callback";
  const res = await request.get(
    `/oauth/authorize?client_id=x&redirect_uri=${encodeURIComponent(redirectUri)}`,
    { maxRedirects: 0 },
  );
  expect(res.status()).toBe(307);
  const login = new URL(res.headers()["location"]!, "http://x");
  expect(login.pathname).toBe("/login");
  const next = new URL(login.searchParams.get("next")!, "http://x");
  expect(next.searchParams.get("redirect_uri")).toBe(redirectUri);
});
