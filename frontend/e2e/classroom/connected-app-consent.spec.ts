import { createHash, randomBytes } from "node:crypto";

import { expect, test } from "@playwright/test";

import { establishClassroomSession } from "./lib/cross-app-session";

// 연결된 앱의 동의 화면 (#512, ADR-0052) — 이 기능이 남기는 유일한 e2e 다(spec #511
// 「Testing Decisions」). 등록·토큰·MCP 호출은 백엔드 HTTP 시험이 고정하고, 여기서는
// 백엔드 시험이 볼 수 없는 것 — 강의실 앱이 `/oauth/register` 를 백엔드로 넘기고, 로그인한
// 강사가 동의 화면에서 「허락」을 누르면 브라우저가 코드를 들고 앱의 주소로 돌아가는가 —
// 만 본다.
const REDIRECT_URI = "https://connector.example.test/callback";

test("로그인한 강사가 동의 화면에서 허락하면 앱으로 코드가 돌아간다", async ({ page, baseURL }) => {
  await establishClassroomSession(page, `connected-app-consent-${Date.now()}`);

  const registered = await page.context().request.post("/oauth/register", {
    data: { client_name: "e2e 커넥터", redirect_uris: [REDIRECT_URI], token_endpoint_auth_method: "none" },
  });
  expect(registered.status()).toBe(201);
  const { client_id: clientId } = (await registered.json()) as { client_id: string };

  const verifier = randomBytes(48).toString("base64url");
  const challenge = createHash("sha256").update(verifier).digest("base64url");
  const query = new URLSearchParams({
    response_type: "code",
    client_id: clientId,
    redirect_uri: REDIRECT_URI,
    code_challenge: challenge,
    code_challenge_method: "S256",
    state: "e2e-state",
    scope: "classroom",
  });

  // 앱의 콜백은 바깥 주소라 실제로 나가지 않게 이 자리에서 받는다.
  await page.context().route("https://connector.example.test/**", (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: "<p>ok</p>" }),
  );

  await page.goto(`/oauth/authorize?${query.toString()}`);
  await expect(page.getByTestId("consent-heading")).toHaveText("e2e 커넥터을(를) 연결할까요?");

  const [callback] = await Promise.all([
    page.waitForRequest((request) => request.url().startsWith(REDIRECT_URI)),
    page.getByTestId("consent-approve").click(),
  ]);
  const returned = new URL(callback.url()).searchParams;
  expect(returned.get("code")).toBeTruthy();
  expect(returned.get("state")).toBe("e2e-state");
  expect(returned.get("iss")).toBe(new URL(baseURL!).origin);
});

// Codex CLI 같은 로컬 앱의 콜백은 루프백 주소다(#622). Next 의 NextURL 은 쿼리 안 127.0.0.1 을
// localhost 로 바꿔 파싱하므로, 프록시가 쿼리를 그대로 넘기지 않으면 백엔드가 등록한
// redirect_uri 와 글자가 달라 동의 화면이 「앱이 등록한 주소와 돌아갈 주소가 다릅니다」로
// 거절한다.
test("루프백 127.0.0.1 redirect_uri 로 등록한 앱도 허락하면 그 주소로 코드가 돌아간다", async ({ page }) => {
  const loopback = "http://127.0.0.1:59884/callback";
  await establishClassroomSession(page, `connected-app-loopback-${Date.now()}`);

  const registered = await page.context().request.post("/oauth/register", {
    data: { client_name: "e2e 로컬 앱", redirect_uris: [loopback], token_endpoint_auth_method: "none" },
  });
  expect(registered.status()).toBe(201);
  const { client_id: clientId } = (await registered.json()) as { client_id: string };

  const challenge = createHash("sha256").update(randomBytes(48).toString("base64url")).digest("base64url");
  const query = new URLSearchParams({
    response_type: "code",
    client_id: clientId,
    redirect_uri: loopback,
    code_challenge: challenge,
    code_challenge_method: "S256",
    state: "e2e-loopback",
    scope: "classroom",
  });
  await page.context().route("http://127.0.0.1:59884/**", (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: "<p>ok</p>" }),
  );

  await page.goto(`/oauth/authorize?${query.toString()}`);
  await expect(page.getByTestId("consent-heading")).toHaveText("e2e 로컬 앱을(를) 연결할까요?");

  const [callback] = await Promise.all([
    page.waitForRequest((request) => request.url().startsWith(loopback)),
    page.getByTestId("consent-approve").click(),
  ]);
  const returned = new URL(callback.url()).searchParams;
  expect(returned.get("code")).toBeTruthy();
  expect(returned.get("state")).toBe("e2e-loopback");
});
