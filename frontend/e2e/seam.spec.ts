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

// 이 앱은 BFF 다(ADR-0016). 백엔드에 닿지 못하면 로그인부터 아무것도 되지 않으므로,
// "Next 는 떴는데 백엔드를 못 찾는" 상태가 초록으로 보이면 안 된다. 그래서 헬스는
// 백엔드 도달 여부까지 답하고, 못 닿으면 503 이다.
//
// 못 닿는 경로(503 / degraded)는 이 시임에서 테스트하지 않는다 — 백엔드를 못 보는
// 두 번째 앱 인스턴스가 필요한데, 시임을 하나로 유지하는 값이 그보다 크다.
// 구현 시 백엔드 주소를 죽은 포트로 돌린 인스턴스로 직접 확인했다(503 + unreachable).
test("브라우저 없이 raw HTTP 로 친 헬스 엔드포인트가 백엔드 도달까지 답한다", async ({
  request,
}) => {
  const res = await request.get("/healthz");

  expect(res.status()).toBe(200);
  expect(await res.json()).toMatchObject({
    status: "ok",
    frontend: "ok",
    backend: "ok",
  });
});

// 공개 표면은 서버에서 렌더링되어야 색인된다(ADR-0015). 여기서 그 검증 기법을 세운다.
//
// **주의 — 이 기법의 한계를 알고 확장해야 한다.** Next 는 클라이언트 컴포넌트도 초기
// 요청에 서버 프리렌더하므로, HTML 에 마크업이 들어 있다는 사실만으로는 `"use client"`
// 실수를 잡지 못한다. 실제로 갈리는 것은 **백엔드에서 온 데이터**다 — 클라이언트에서
// 가져오면 그 데이터가 초기 HTML 에 없다.
//
// 그러므로 FE-04(공모전 목록)·FE-06(개발자 프로필)은 이 파일을 복사하되
// **백엔드가 준 값**(공모전 제목, 상금, 프로필 이름 같은 것)이 JS 없이 받은 HTML 에
// 들어 있는지를 단언해야 한다. 뼈대 페이지에는 아직 그 데이터가 없다.
test.describe("자바스크립트 없이", () => {
  test.use({ javaScriptEnabled: false });

  test("페이지 내용이 그대로 보인다", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1, name: "Laurio" })).toBeVisible();
  });
});
