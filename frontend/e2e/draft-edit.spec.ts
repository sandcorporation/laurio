import { expect, test } from "@playwright/test";

// 결제 전까지는 초안을 고칠 수 있다 — 파생값도 다시 계산된다 (#113, 부모 #110).
//
// draft.spec.ts(#111)와 같은 관용구(fake 로그인 → dev 본인확인 → 브리프 제출)로
// 초안을 만든 뒤, 이 스펙은 그 위에 편집을 얹는다. 판정(최소 상금 합계·상금미달)
// 은 화면이 계산하지 않고 서버 응답을 그대로 읽는다는 것도 함께 확인한다.

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

async function createDraftViaForm(
  page: import("@playwright/test").Page,
  runId: string,
  options: { prize: number; deliverableTypeName?: string; categoryName?: string },
): Promise<number> {
  const categoryId = await findByName(page, "/api/backend/contests/categories", options.categoryName ?? "게임");
  const deliverableTypeId = await findByName(
    page,
    "/api/backend/contests/deliverable-types",
    options.deliverableTypeName ?? "랜딩·원페이지",
  );

  await page.goto("/console/contests/new");
  await expect(page.getByTestId("grill-brief-heading")).toBeVisible();

  await page.getByTestId("grill-brief-title").fill(`[E2E] 초안 편집 테스트 ${runId}`);
  await page.getByTestId("grill-brief-category").selectOption(String(categoryId));
  await page.getByTestId(`grill-brief-deliverable-type-${deliverableTypeId}-checkbox`).check();
  await page.getByTestId("grill-brief-prize").fill(String(options.prize));
  await page.getByTestId("grill-brief-deadline").fill(futureLocalDatetime(10));

  await page.getByTestId("grill-brief-submit").click();
  await expect(page).toHaveURL(/\/console\/contests\/\d+\/draft/);
  await expect(page.getByTestId("grill-draft-panel")).toBeVisible();

  const match = page.url().match(/\/console\/contests\/(\d+)\/draft/);
  expect(match).not.toBeNull();
  return Number(match![1]);
}

test.describe("결제 전까지는 초안을 고칠 수 있다", () => {
  test("제목·설명·카테고리·상금·마감을 고치면 다시 읽었을 때 그 값이다", async ({ page }) => {
    const runId = `${Date.now()}`;
    await login(page, `draft-edit-fields-${runId}`);
    await verify(page, `draft-edit-fields-${runId}`);
    const contestId = await createDraftViaForm(page, runId, { prize: 1_000_000, categoryName: "게임" });

    const otherCategoryId = await findByName(page, "/api/backend/contests/categories", "교육");

    await expect(page.getByTestId("draft-editable-notice")).toBeVisible();
    await page.getByTestId("draft-edit-brief-toggle").click();

    await page.getByTestId("draft-edit-title").fill(`[E2E] 고친 제목 ${runId}`);
    await page.getByTestId("draft-edit-category").selectOption(String(otherCategoryId));
    await page.getByTestId("draft-edit-prize").fill("9000000");
    await page.getByTestId("draft-edit-deadline").fill(futureLocalDatetime(20));
    await page.getByTestId("draft-edit-description").fill("고친 설명입니다");
    await page.getByTestId("draft-edit-save").click();

    // 저장되면 폼이 닫히고 읽기 화면으로 돌아간다.
    await expect(page.getByTestId("draft-edit-title")).toHaveCount(0);
    await expect(page.getByTestId("grill-draft-title")).toContainText(`[E2E] 고친 제목 ${runId}`);
    await expect(page.getByTestId("grill-draft-prize")).toHaveText("9,000,000");

    // 새로고침해도(서버에서 다시 읽어도) 그대로다 — POST/PATCH 응답에만 기댄
    // 것이 아니다.
    await page.reload();
    await expect(page.getByTestId("grill-draft-title")).toContainText(`[E2E] 고친 제목 ${runId}`);
    await expect(page.getByTestId("grill-draft-prize")).toHaveText("9,000,000");

    const reread = await page.evaluate(async (id) => {
      const res = await fetch(`/api/backend/contests/${id}`);
      return res.json();
    }, contestId);
    expect(reread.category.id).toBe(otherCategoryId);
    expect(reread.description).toBe("고친 설명입니다");
  });

  test("요구형태나 상금을 바꾸면 최소 상금 합계와 미달 표시가 함께 바뀐다 — 화면은 서버 값을 그대로 읽는다", async ({
    page,
  }) => {
    const runId = `${Date.now()}`;
    await login(page, `draft-edit-underfunded-${runId}`);
    await verify(page, `draft-edit-underfunded-${runId}`);
    // 랜딩·원페이지(20만) 하나로 30만 상금 — 미달이 아니다.
    const contestId = await createDraftViaForm(page, runId, {
      prize: 300_000,
      deliverableTypeName: "랜딩·원페이지",
    });
    await expect(page.getByTestId("grill-underfunded-badge")).toHaveCount(0);

    const webTypeId = await findByName(page, "/api/backend/contests/deliverable-types", "웹 서비스");

    await page.getByTestId("draft-edit-brief-toggle").click();
    // 웹 서비스(100만)를 추가로 선택 — 합계(120만)가 30만 상금을 넘는다.
    await page.getByTestId(`draft-edit-deliverable-type-${webTypeId}-checkbox`).check();
    await page.getByTestId("draft-edit-save").click();

    await expect(page.getByTestId("grill-underfunded-badge")).toBeVisible();

    // 화면이 스스로 계산한 것이 아니라 서버 값 그대로다.
    const afterTypeChange = await page.evaluate(async (id) => {
      const res = await fetch(`/api/backend/contests/${id}`);
      return res.json();
    }, contestId);
    expect(afterTypeChange.is_underfunded).toBe(true);
    await expect(page.getByTestId("grill-draft-minimum-total")).toHaveText(
      afterTypeChange.required_minimum_prize.toLocaleString("ko-KR"),
    );

    // 상금을 충분히 올리면(요구형태는 그대로) 미달이 풀린다.
    await page.getByTestId("draft-edit-brief-toggle").click();
    await page.getByTestId("draft-edit-prize").fill("5000000");
    await page.getByTestId("draft-edit-save").click();

    await expect(page.getByTestId("grill-underfunded-badge")).toHaveCount(0);
  });

  test("요구형태를 바꿔도 이미 붙인 Requirement가 지워지지 않고, 화면이 바뀐 사실을 알린다", async ({
    page,
  }) => {
    const runId = `${Date.now()}`;
    await login(page, `draft-edit-keep-req-${runId}`);
    await verify(page, `draft-edit-keep-req-${runId}`);
    const contestId = await createDraftViaForm(page, runId, {
      prize: 5_000_000,
      deliverableTypeName: "랜딩·원페이지",
    });

    await page.getByTestId("grill-manual-add-open").click();
    await page.getByTestId("grill-manual-add-text").fill("다크모드를 지원한다");
    await page.getByTestId("grill-manual-add-submit").click();
    await expect(page.getByTestId("grill-requirement-counts")).toHaveText("필수 1 · 선택 0");

    const adminTypeId = await findByName(page, "/api/backend/contests/deliverable-types", "관리자 페이지");
    await expect(page.getByTestId("draft-deliverable-types-changed-notice")).toHaveCount(0);

    await page.getByTestId("draft-edit-brief-toggle").click();
    await page.getByTestId(`draft-edit-deliverable-type-${adminTypeId}-checkbox`).check();
    await page.getByTestId("draft-edit-save").click();

    // 지워지지 않았다.
    await expect(page.getByTestId("grill-requirement-counts")).toHaveText("필수 1 · 선택 0");
    await expect(page.locator('[data-testid$="-text"]').first()).toContainText("다크모드를 지원한다");

    // 바뀐 사실을 화면이 알린다.
    await expect(page.getByTestId("draft-deliverable-types-changed-notice")).toBeVisible();
    await page.getByTestId("draft-deliverable-types-changed-dismiss").click();
    await expect(page.getByTestId("draft-deliverable-types-changed-notice")).toHaveCount(0);

    const reread = await page.evaluate(async (id) => {
      const res = await fetch(`/api/backend/contests/${id}`);
      return res.json();
    }, contestId);
    expect(reread.requirements).toHaveLength(1);
  });

  test("결제된 Contest를 고치려 하면 분명히 거절당한다 — 편집 화면 자체가 닫혀 있다", async ({
    page,
  }) => {
    const runId = `${Date.now()}`;
    await login(page, `draft-edit-paid-${runId}`);
    await verify(page, `draft-edit-paid-${runId}`);
    const contestId = await createDraftViaForm(page, runId, { prize: 5_000_000 });

    await page.goto(`/console/contests/${contestId}/payment`);
    await page.getByTestId("payment-pay-button").click();
    await expect(page.getByTestId("payment-success")).toBeVisible();

    // draft 화면 자체가 편집 UI를 그리지 않는다(#111이 이미 세운 "closed" 상태).
    await page.goto(`/console/contests/${contestId}/draft`);
    await expect(page.getByTestId("draft-closed")).toBeVisible();
    await expect(page.getByTestId("draft-edit-brief-toggle")).toHaveCount(0);

    // API를 직접 쳐도 조용히 넘어가지 않는다 — 409로 분명히 거절한다.
    const patchStatus = await page.evaluate(async (id) => {
      const res = await fetch(`/api/backend/contests/${id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title: "결제된 뒤 몰래 고치기" }),
      });
      return res.status;
    }, contestId);
    expect(patchStatus).toBe(409);
  });

  test("남의 Contest는 고칠 수 없다 — 있는지가 아니라 없는지로 단언한다", async ({ page }) => {
    const runId = `${Date.now()}`;
    await login(page, `draft-edit-owner-${runId}`);
    await verify(page, `draft-edit-owner-${runId}`);
    const contestId = await createDraftViaForm(page, runId, { prize: 5_000_000 });

    await login(page, `draft-edit-stranger-${runId}`);
    const patchStatus = await page.evaluate(async (id) => {
      const res = await fetch(`/api/backend/contests/${id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title: "남의 초안을 몰래 고치기" }),
      });
      return res.status;
    }, contestId);
    expect(patchStatus).toBe(404);
  });

  test("유효하지 않은 값이면 저장 버튼이 막히고 이유가 보인다 — 눌러도 아무 일도 안 하는 것처럼 보이지 않는다", async ({
    page,
  }) => {
    // 코드리뷰 지적 3 — 예전에는 상금·요구형태·마감·카테고리 중 하나라도
    // 비어 있으면 submit()이 조용히 리턴해, 저장을 눌러도 클릭이 씹힌 것처럼
    // 보였다. 지금은 버튼도 막히고 이유도 보인다.
    const runId = `${Date.now()}`;
    await login(page, `draft-edit-invalid-${runId}`);
    await verify(page, `draft-edit-invalid-${runId}`);
    await createDraftViaForm(page, runId, { prize: 5_000_000, deliverableTypeName: "랜딩·원페이지" });

    await page.getByTestId("draft-edit-brief-toggle").click();

    // 상금을 비운다.
    await page.getByTestId("draft-edit-prize").fill("");
    await expect(page.getByTestId("draft-edit-save")).toBeDisabled();
    await expect(page.getByTestId("draft-edit-validation-hint")).toContainText(
      "상금은 0보다 큰 금액이어야 합니다",
    );

    // 상금을 되돌리면 버튼이 다시 풀린다.
    await page.getByTestId("draft-edit-prize").fill("5000000");
    await expect(page.getByTestId("draft-edit-save")).toBeEnabled();
    await expect(page.getByTestId("draft-edit-validation-hint")).toHaveCount(0);

    // 요구형태를 전부 해제한다.
    const landingId = await findByName(page, "/api/backend/contests/deliverable-types", "랜딩·원페이지");
    await page.getByTestId(`draft-edit-deliverable-type-${landingId}-checkbox`).uncheck();
    await expect(page.getByTestId("draft-edit-save")).toBeDisabled();
    await expect(page.getByTestId("draft-edit-validation-hint")).toContainText(
      "요구형태를 하나 이상 선택해주세요",
    );

    // 요구형태를 다시 고르고, 이번엔 마감을 비운다.
    await page.getByTestId(`draft-edit-deliverable-type-${landingId}-checkbox`).check();
    await page.getByTestId("draft-edit-deadline").fill("");
    await expect(page.getByTestId("draft-edit-save")).toBeDisabled();
    await expect(page.getByTestId("draft-edit-validation-hint")).toContainText("마감 기한을 선택해주세요");
  });
});
