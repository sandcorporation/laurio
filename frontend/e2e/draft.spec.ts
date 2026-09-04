import { expect, test } from "@playwright/test";

// 초안 이어서 작성 (#111, 부모 #110).
//
// draft Contest가 브라우저 메모리에만 살던 문제를 고친다 — URL로 식별하고
// 서버에서 다시 읽으므로 새로고침·북마크·목록 재진입이 전부 이어진다. 이
// 스펙은 grill.spec.ts/payment.spec.ts와 같은 관용구(fake 로그인 → dev
// 본인확인 → 브리프 제출)를 그대로 쓴다 — 시임은 실행 중인 앱 하나다
// (ADR-0017).

async function login(page: import("@playwright/test").Page, seed: string): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("fake-login-seed").fill(seed);
  await page.getByTestId("login-kakao").click();
  await expect(page).toHaveURL(/\/console/, { timeout: 15_000 });
}

async function verify(page: import("@playwright/test").Page, seed: string): Promise<void> {
  const status = await page.evaluate(async (s) => {
    const res = await fetch("/api/backend/verification/verify", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ verification_token: `${s}|1990-01-01|ci-${s}|di-${s}` }),
    });
    return res.status;
  }, seed);
  expect(status).toBe(200);
}

async function findByName(
  page: import("@playwright/test").Page,
  path: string,
  name: string,
): Promise<number> {
  const id = await page.evaluate(
    async ({ path, name }) => {
      const res = await fetch(path);
      const list = (await res.json()) as { id: number; name: string }[];
      return list.find((item) => item.name === name)?.id ?? null;
    },
    { path, name },
  );
  expect(id, `"${name}"을(를) ${path}에서 찾지 못했다`).not.toBeNull();
  return id as number;
}

function futureLocalDatetime(daysAhead: number): string {
  const d = new Date(Date.now() + daysAhead * 24 * 60 * 60 * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 브리프 폼을 채워 draft Contest를 만들고, 화면이 넘어간 draft URL에서
 * id를 읽어 돌려준다(#111 — 이제는 URL 자체에 id가 있다). */
async function createDraftViaForm(
  page: import("@playwright/test").Page,
  runId: string,
  prize = 5_000_000,
): Promise<number> {
  const categoryId = await findByName(page, "/api/backend/contests/categories", "게임");
  const deliverableTypeId = await findByName(
    page,
    "/api/backend/contests/deliverable-types",
    "웹 서비스",
  );

  await page.goto("/console/contests/new");
  await expect(page.getByTestId("grill-brief-heading")).toBeVisible();

  await page.getByTestId("grill-brief-title").fill(`[E2E] 초안 이어쓰기 테스트 ${runId}`);
  await page.getByTestId("grill-brief-category").selectOption(String(categoryId));
  await page.getByTestId(`grill-brief-deliverable-type-${deliverableTypeId}-checkbox`).check();
  await page.getByTestId("grill-brief-prize").fill(String(prize));
  await page.getByTestId("grill-brief-deadline").fill(futureLocalDatetime(10));

  await page.getByTestId("grill-brief-submit").click();
  await expect(page).toHaveURL(/\/console\/contests\/\d+\/draft/);
  await expect(page.getByTestId("grill-draft-panel")).toBeVisible();

  const match = page.url().match(/\/console\/contests\/(\d+)\/draft/);
  expect(match).not.toBeNull();
  return Number(match![1]);
}

test.describe("초안이 URL을 갖는다 — 새로고침해도, 며칠 뒤에도", () => {
  test("브리프를 제출하면 draft의 URL로 넘어가고, 새로고침해도 브리프와 붙여둔 Requirement가 그대로다", async ({
    page,
  }) => {
    const runId = `${Date.now()}`;
    await login(page, `draft-refresh-${runId}`);
    await verify(page, `draft-refresh-${runId}`);

    const contestId = await createDraftViaForm(page, runId, 5_000_000);

    // 대화로 요구사항 하나를 붙여둔다.
    await page.getByTestId("grill-chat-input").fill("로그인 기능이 필요합니다");
    await page.getByTestId("grill-chat-send").click();
    await expect(page.getByTestId("grill-proposal-0")).toBeVisible();
    await page.getByTestId("grill-proposal-0-add").click();
    await expect(page.getByTestId("grill-requirement-counts")).toHaveText("필수 1 · 선택 0");

    // 생성 응답에만 의존한 것이 아니라는 것을 새로고침으로 증명한다 — 화면
    // 상태를 전부 버리고 URL만으로 다시 읽는다.
    await page.reload();

    await expect(page).toHaveURL(new RegExp(`/console/contests/${contestId}/draft`));
    await expect(page.getByTestId("grill-draft-title")).toContainText(`[E2E] 초안 이어쓰기 테스트 ${runId}`);
    await expect(page.getByTestId("grill-draft-prize")).toHaveText("5,000,000");
    await expect(page.getByTestId("grill-requirement-counts")).toHaveText("필수 1 · 선택 0");
  });

  test("브리프 · 요구사항 · 결제 세 단계가 보이고, 지금 어느 단계인지 읽힌다", async ({ page }) => {
    const runId = `${Date.now()}`;
    await login(page, `draft-stepper-${runId}`);
    await verify(page, `draft-stepper-${runId}`);
    await createDraftViaForm(page, runId);

    await expect(page.getByTestId("contest-stage-stepper")).toBeVisible();
    await expect(page.getByTestId("contest-stage-brief")).toBeVisible();
    await expect(page.getByTestId("contest-stage-requirements")).toBeVisible();
    await expect(page.getByTestId("contest-stage-payment")).toBeVisible();
    expect(await page.getByTestId("contest-stage-requirements").getAttribute("data-current")).toBe("true");
    expect(await page.getByTestId("contest-stage-brief").getAttribute("data-current")).toBe("false");
  });

  test("결제 화면에서 요구사항으로 클릭으로 돌아간다", async ({ page }) => {
    const runId = `${Date.now()}`;
    await login(page, `draft-back-${runId}`);
    await verify(page, `draft-back-${runId}`);
    const contestId = await createDraftViaForm(page, runId);

    await page.getByTestId("grill-go-to-payment").click();
    await expect(page).toHaveURL(new RegExp(`/console/contests/${contestId}/payment`));

    await expect(page.getByTestId("payment-back-to-requirements")).toBeVisible();
    await page.getByTestId("payment-back-to-requirements").click();
    await expect(page).toHaveURL(new RegExp(`/console/contests/${contestId}/draft`));
    await expect(page.getByTestId("grill-draft-panel")).toBeVisible();
  });

  test("내 공모전 목록의 초안 행을 누르면 결제 화면이 아니라 이어서 작성하는 자리로 간다", async ({
    page,
  }) => {
    const runId = `${Date.now()}`;
    await login(page, `draft-list-${runId}`);
    await verify(page, `draft-list-${runId}`);
    const contestId = await createDraftViaForm(page, runId);

    await page.goto("/console/contests");
    const row = page.getByTestId(`my-contest-row-${contestId}`);
    await expect(row).toBeVisible();
    expect(await row.getAttribute("data-next-action")).toBe("pay_to_publish");

    await page.getByTestId(`my-contest-row-${contestId}-detail`).click();
    await expect(page).toHaveURL(new RegExp(`/console/contests/${contestId}/draft`));
    await expect(page.getByTestId("grill-draft-panel")).toBeVisible();
  });

  test("결제가 끝난 뒤에는 이 화면으로의 편집 이동이 닫힌다", async ({ page }) => {
    const runId = `${Date.now()}`;
    await login(page, `draft-closed-${runId}`);
    await verify(page, `draft-closed-${runId}`);
    const contestId = await createDraftViaForm(page, runId);

    await page.goto(`/console/contests/${contestId}/payment`);
    await page.getByTestId("payment-pay-button").click();
    await expect(page.getByTestId("payment-success")).toBeVisible();

    // 결제된 뒤에도 이 화면에서는 "요구사항으로 돌아가기" 링크가 없다.
    await expect(page.getByTestId("payment-back-to-requirements")).toHaveCount(0);

    // 결제된 뒤에 draft URL을 직접 열어도 편집 UI(대화·체크리스트)로 돌아가지
    // 않는다.
    await page.goto(`/console/contests/${contestId}/draft`);
    await expect(page.getByTestId("draft-closed")).toBeVisible();
    await expect(page.getByTestId("grill-chat-panel")).toHaveCount(0);
    await expect(page.getByTestId("grill-draft-panel")).toHaveCount(0);
    await expect(page.getByTestId("draft-view-contest")).toBeVisible();
  });

  test("남의 초안에는 닿을 수 없다 — 있는지가 아니라 없는지로 단언한다", async ({ page }) => {
    const runId = `${Date.now()}`;
    await login(page, `draft-owner-${runId}`);
    await verify(page, `draft-owner-${runId}`);
    const contestId = await createDraftViaForm(page, runId);

    await login(page, `draft-stranger-${runId}`);
    await page.goto(`/console/contests/${contestId}/draft`);

    await expect(page.getByTestId("draft-not-found")).toBeVisible();
    await expect(page.getByTestId("grill-draft-panel")).toHaveCount(0);
    await expect(page.getByTestId("grill-draft-title")).toHaveCount(0);
  });

  test("세션이 없으면 렌더링 전에 로그인으로 돌아간다 — 보호된 내용이 응답에 없다", async ({
    page,
  }) => {
    const response = await page.goto("/console/contests/1/draft");

    expect(response?.status()).toBeLessThan(400);
    await expect(page).toHaveURL(/\/login/);
    expect(await page.content()).not.toContain("grill-draft-panel");
  });

  test("대화 이력·카테고리·요구형태 조회 중 하나가 네트워크 수준에서 실패해도 화면은 죽지 않는다", async ({
    page,
  }) => {
    // 코드리뷰 지적 5 — Contest 자체는 정상 읽혔는데(요청이 아예 서버에 닿지도
    // 못하는) 나머지 세 "부가" 조회 중 하나가 reject되면, 예전에는
    // `Promise.all`이 전체를 reject시켜 이미 확인한 Contest까지 통째로 에러
    // 화면으로 덮었다 — "이 조회들이 실패해도 화면 자체는 죽지 않는다"는
    // 주석과 실제 동작이 어긋나 있었다.
    const runId = `${Date.now()}`;
    await login(page, `draft-partial-fail-${runId}`);
    await verify(page, `draft-partial-fail-${runId}`);
    const contestId = await createDraftViaForm(page, runId, 5_000_000);

    await page.route("**/api/backend/contests/categories", (route) => route.abort());

    await page.goto(`/console/contests/${contestId}/draft`);

    // 화면은 여전히 정상적으로 뜬다 — 에러 화면으로 떨어지지 않는다.
    await expect(page.getByTestId("grill-draft-panel")).toBeVisible();
    await expect(page.getByTestId("draft-load-error")).toHaveCount(0);
    await expect(page.getByTestId("grill-draft-title")).toContainText(`[E2E] 초안 이어쓰기 테스트 ${runId}`);
  });
});
