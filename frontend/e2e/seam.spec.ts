import { expect, test } from "@playwright/test";

// 이 파일이 증명하는 것은 화면이 아니라 **시임**이다(ADR-0017).
//
// 실행 중인 Next 앱 하나가 유일한 진입점이고, 브라우저를 쓰는 테스트와 raw HTTP 를
// 쓰는 테스트가 그 같은 입구를 통과한다. 이후 티켓들이 이 위에 얹힌다 — 프록시
// 허용목록과 Origin 검증(FE-08)은 브라우저 없이 `request` 로, 화면 흐름은 `page` 로.

test("브라우저로 연 홈이 렌더링된다", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Laurio" })).toBeVisible();
});

test("브라우저 없이 raw HTTP 로 친 헬스 엔드포인트가 응답한다", async ({ request }) => {
  const res = await request.get("/healthz");

  expect(res.status()).toBe(200);
  expect(await res.json()).toMatchObject({
    status: "ok",
    frontend: "ok",
    backend: "ok",
  });
});

// 이 앱은 BFF 다(ADR-0016). 백엔드에 닿지 못하면 로그인부터 아무것도 되지 않으므로,
// "Next 는 떴는데 백엔드를 못 찾는" 상태가 초록으로 보이면 안 된다.
test("헬스 엔드포인트가 백엔드 도달 여부까지 답한다", async ({ request }) => {
  const body = await (await request.get("/healthz")).json();

  expect(body.backend).toBe("ok");
});

// 공개 표면은 서버에서 렌더링되어야 색인된다(ADR-0015). 여기서 그 검증 기법을
// 세워둔다 — 브라우저 없이 받은 HTML 안에 내용이 이미 들어 있는지 본다.
// 실제 공개 페이지(공모전 목록·개발자 프로필)에는 FE-04·FE-06 이 이 기법을 적용한다.
test("서버가 돌려준 HTML 에 내용이 이미 들어 있다", async ({ request }) => {
  const html = await (await request.get("/")).text();

  expect(html).toContain("<h1>Laurio</h1>");
});
