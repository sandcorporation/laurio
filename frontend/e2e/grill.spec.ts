import { expect, test } from "@playwright/test";

// AI grill 개최 (FE-12, #37, spec #25 User Story 40-48).
//
// 이 화면이 만드는 Requirement 체크리스트는 편의 기능이 아니라 Developer의 자가
// 응답·Sponsor의 심사·AI 채점이 공통으로 쓰는 분쟁 예방 장치다(REQUEST.md). 그래서
// 이 스펙은 세 가지를 나란히 확인한다 — ① 대화로 체크리스트가 쌓이고 Sponsor가
// 그것을 수정·삭제·직접 추가할 수 있는지(AI는 제안만 한다), ② 상금미달 배지가
// 최소 상금 합산(백엔드 POST /contests/quote 기준, 프론트가 다시 계산하지 않는다)에
// 따라 등록 전에 보이고 그래도 개최를 막지 않는지, ③ LLM이 이상하거나 형식에
// 맞지 않는 응답을 해도 화면이 죽지 않는지(모델의 예상 밖 응답은 정상 운영
// 조건이다) — 전부 dev compose의 fake LLM 어댑터(ADR-0007)로, 실제 LLM 없이 돈다.

async function login(page: import("@playwright/test").Page, seed: string): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("fake-login-seed").fill(seed);
  await page.getByTestId("login-kakao").click();
  await expect(page).toHaveURL(/\/console/);
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

// "grill-proposal-0"의 testid 접두어를 "grill-proposal-0-add"(추가 버튼)도
// 공유한다 — `^="grill-proposal-"`만으로는 버튼까지 두 배로 잡힌다. 항목
// 개수를 셀 때는 항상 이 헬퍼로 버튼을 제외한다.
function proposalItems(page: import("@playwright/test").Page) {
  return page.locator('[data-testid^="grill-proposal-"]:not([data-testid$="-add"])');
}

// 말풍선 바깥 div(testid: grill-chat-message-N)에는 role="assistant"일 때
// "AI" 아바타 라벨도 형제로 들어있다 — role별로 걸러 쓸 때는 `[data-role]`이
// 붙은 바깥 요소만, 정확한 발화 텍스트가 필요할 때는 안쪽 "-content" 자식을 쓴다.
function chatBubbles(page: import("@playwright/test").Page) {
  return page.locator('[data-testid^="grill-chat-message-"][data-role]');
}

function assistantBubbles(page: import("@playwright/test").Page) {
  return page.locator('[data-testid^="grill-chat-message-"][data-role="assistant"]');
}

function futureLocalDatetime(daysAhead: number): string {
  const d = new Date(Date.now() + daysAhead * 24 * 60 * 60 * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** dev 시드가 이미 심어둔 baseline DeliverableType/Category(core.seed_dev_data)에서
 * 이름으로 id를 찾는다 — 실행 환경마다 auto-increment id가 달라질 수 있어서다. */
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

/** 브리프 폼을 채워 Phase A를 통과하고, 방금 만들어진 draft Contest의 id를
 * 응답에서 직접 읽어 돌려준다(화면 URL에는 id가 없다 — Phase A/B는 같은 경로
 * 안의 화면 상태 전환이다). */
async function createDraftViaForm(
  page: import("@playwright/test").Page,
  runId: string,
  options: { prize: number; deliverableTypeName?: string; categoryName?: string },
): Promise<number> {
  const categoryId = await findByName(page, "/api/backend/contests/categories", options.categoryName ?? "게임");
  const deliverableTypeId = await findByName(
    page,
    "/api/backend/contests/deliverable-types",
    options.deliverableTypeName ?? "웹 서비스",
  );

  await page.goto("/console/contests/new");
  await expect(page.getByTestId("grill-brief-heading")).toBeVisible();

  await page.getByTestId("grill-brief-title").fill(`[E2E] AI grill 테스트 ${runId}`);
  await page.getByTestId("grill-brief-category").selectOption(String(categoryId));
  await page.getByTestId(`grill-brief-deliverable-type-${deliverableTypeId}-checkbox`).check();
  await page.getByTestId("grill-brief-prize").fill(String(options.prize));
  await page.getByTestId("grill-brief-deadline").fill(futureLocalDatetime(10));

  const [response] = await Promise.all([
    page.waitForResponse(
      (res) => res.url().endsWith("/api/backend/contests") && res.request().method() === "POST",
    ),
    page.getByTestId("grill-brief-submit").click(),
  ]);
  const body = (await response.json()) as { id: number };

  await expect(page.getByTestId("grill-draft-panel")).toBeVisible();
  return body.id;
}

test.describe("브리프 → 실시간 최소 상금 합산 → AI 대화로 체크리스트 구성", () => {
  test("요구형태를 복수 선택하면 최소 상금이 실시간 합산되고, 상금미달 배지가 등록 전부터 보이며, 미달이어도 개최할 수 있다", async ({
    page,
  }) => {
    const runId = `${Date.now()}`;
    await login(page, `grill-brief-${runId}`);
    await verify(page, `grill-brief-${runId}`);

    const categoryId = await findByName(page, "/api/backend/contests/categories", "게임");
    const landingId = await findByName(page, "/api/backend/contests/deliverable-types", "랜딩·원페이지");
    const adminId = await findByName(page, "/api/backend/contests/deliverable-types", "관리자 페이지");

    await page.goto("/console/contests/new");
    await page.getByTestId("grill-brief-title").fill(`[E2E] AI grill 견적 테스트 ${runId}`);
    await page.getByTestId("grill-brief-category").selectOption(String(categoryId));

    // 하나만 선택했을 때 합계는 그 하나의 최소 제안 상금과 같다.
    await page.getByTestId(`grill-brief-deliverable-type-${landingId}-checkbox`).check();
    await expect(page.getByTestId("grill-brief-quote-total")).toHaveText("200,000");

    // 복수 선택 — 프론트가 직접 더한 게 아니라 POST /contests/quote 응답이 합산했다.
    await page.getByTestId(`grill-brief-deliverable-type-${adminId}-checkbox`).check();
    await expect(page.getByTestId("grill-brief-quote-total")).toHaveText("700,000");

    // 상금을 합계보다 적게 넣으면, 아직 등록(초안 생성)하지 않았는데도 배지 예고가 보인다.
    await page.getByTestId("grill-brief-prize").fill("500000");
    await expect(page.getByTestId("grill-brief-underfunded-preview")).toBeVisible();
    await expect(page.getByTestId("grill-brief-underfunded-preview")).toContainText("700,000");

    await page.getByTestId("grill-brief-deadline").fill(futureLocalDatetime(14));

    // 미달이어도 "개최"(초안 생성)가 거부되지 않는다 — 강제하지 않고 배지로만 신호한다.
    await page.getByTestId("grill-brief-submit").click();
    await expect(page.getByTestId("grill-draft-panel")).toBeVisible();

    await expect(page.getByTestId("grill-draft-minimum-total")).toHaveText("700,000");
    await expect(page.getByTestId("grill-draft-prize")).toHaveText("500,000");
    await expect(page.getByTestId("grill-underfunded-badge")).toBeVisible();
    await expect(page.getByTestId("grill-underfunded-badge")).toContainText("200,000");

    // 결제가 끝나야 공모전이 공개된다는 것이 화면에 있다.
    await expect(page.getByTestId("grill-payment-required-notice")).toHaveText(
      "결제가 끝나야 공모전이 공개됩니다",
    );
  });

  test("여러 턴 대화로 체크리스트가 쌓이고, Sponsor가 수정·삭제·직접 추가까지 할 수 있다", async ({ page }) => {
    const runId = `${Date.now()}`;
    await login(page, `grill-chat-${runId}`);
    await verify(page, `grill-chat-${runId}`);

    await createDraftViaForm(page, runId, { prize: 5_000_000 });

    // 1턴 — 쉼표로 나열한 발화가 후보 여러 개로 쪼개진다.
    await page.getByTestId("grill-chat-input").fill("로그인, 다크모드 지원, 알림 설정");
    await page.getByTestId("grill-chat-send").click();
    await expect(proposalItems(page)).toHaveCount(3);
    await expect(page.getByTestId("grill-proposal-0")).toContainText("로그인");

    // AI 제안은 그 자체로 체크리스트가 되지 않는다 — "추가"를 눌러야 확정된다.
    await expect(page.getByTestId("grill-requirement-empty")).toBeVisible();
    await page.getByTestId("grill-proposal-0-add").click();
    await expect(page.getByTestId("grill-requirement-counts")).toHaveText("필수 1 · 선택 0");
    await expect(page.getByTestId("grill-requirement-empty")).toHaveCount(0);

    // Sponsor가 AI 제안 문구·등급을 직접 고친다.
    await page.locator('[data-testid^="requirement-row-"][data-testid$="-edit"]').first().click();
    const editText = page.locator('[data-testid$="-edit-text"]').first();
    await editText.fill("카카오 로그인을 지원한다");
    await page.locator('[data-testid$="-edit-grade"]').first().selectOption("optional");
    await page.locator('[data-testid$="-save"]').first().click();
    await expect(page.getByTestId("grill-requirement-counts")).toHaveText("필수 0 · 선택 1");
    await expect(page.locator('[data-testid$="-text"]').first()).toContainText("카카오 로그인을 지원한다");

    // Sponsor가 항목을 삭제할 수도 있다.
    await page.locator('[data-testid^="requirement-row-"][data-testid$="-delete"]').first().click();
    await expect(page.getByTestId("grill-requirement-counts")).toHaveText("필수 0 · 선택 0");
    await expect(page.getByTestId("grill-requirement-empty")).toBeVisible();

    // Sponsor가 AI를 거치지 않고 직접 추가할 수도 있다.
    await page.getByTestId("grill-manual-add-open").click();
    await page.getByTestId("grill-manual-add-text").fill("결제 수단으로 카드와 계좌이체를 지원한다");
    await page.getByTestId("grill-manual-add-submit").click();
    await expect(page.getByTestId("grill-requirement-counts")).toHaveText("필수 1 · 선택 0");

    // 2턴째 — 대화가 계속 이어진다("여러 턴에 걸쳐 요구사항을 구체화한다").
    await page.getByTestId("grill-chat-input").fill("테스트 계정도 제공해야 하나요");
    await page.getByTestId("grill-chat-send").click();
    await expect(page.getByTestId("grill-proposal-0")).toContainText("테스트 계정도 제공해야 하나요");
    await expect(chatBubbles(page)).toHaveCount(4);
  });
});

test.describe("LLM 응답 실패 — 대화가 끊기지 않는다", () => {
  test("어댑터가 실패해도 사과 응답으로 감성하고, 대화를 계속 이어갈 수 있다", async ({ page }) => {
    const runId = `${Date.now()}`;
    await login(page, `grill-fail-${runId}`);
    await verify(page, `grill-fail-${runId}`);
    await createDraftViaForm(page, runId, { prize: 5_000_000 });

    // requirement_chat.py `SIMULATED_FAILURE_TRIGGER` — fake 어댑터가 이 문구를
    // 보면 RequirementChatAdapterError를 던진다. 실제 LLM 벤더 장애를 재현with
    // 하는 것과 같은 경로다(#37 인수조건 — "LLM이 이상한 응답을 해도 화면이
    // 죽지 않는다"는 백엔드가 이미 감성한 케이스도 프론트가 그대로 살려낸다).
    await page.getByTestId("grill-chat-input").fill("[[e2e-simulate-llm-failure]] 아무 기능이나 만들어주세요");
    await page.getByTestId("grill-chat-send").click();

    await expect(proposalItems(page)).toHaveCount(0);
    const lastAssistantBubble = assistantBubbles(page).last();
    await expect(lastAssistantBubble).toContainText("일시적으로 제안을 만들지 못했어요");

    // 대화가 끊기지 않았다 — 이어서 정상 발화를 보내면 다시 제안을 받는다.
    await page.getByTestId("grill-chat-input").fill("로그인 기능이 꼭 있어야 합니다");
    await page.getByTestId("grill-chat-send").click();
    await expect(page.getByTestId("grill-proposal-0")).toContainText("로그인 기능이 꼭 있어야 합니다");
  });
});

test.describe("LLM 응답이 이상하거나 형식에 맞지 않아도 화면이 죽지 않는다", () => {
  test("JSON이 아닌 응답 · 필드 누락 · 타입이 다른 필드 · 터무니없이 긴 문자열 · 응답 없음", async ({ page }) => {
    const runId = `${Date.now()}`;
    await login(page, `grill-malformed-${runId}`);
    await verify(page, `grill-malformed-${runId}`);
    const contestId = await createDraftViaForm(page, runId, { prize: 5_000_000 });
    const chatUrl = `**/api/backend/contests/${contestId}/requirement-chat/messages`;

    const pageErrors: string[] = [];
    page.on("pageerror", (err) => pageErrors.push(String(err)));

    async function sendUnderRoute(message: string) {
      await page.getByTestId("grill-chat-input").fill(message);
      await page.getByTestId("grill-chat-send").click();
      // 화면이 죽지 않았다 — 입력창이 여전히 상호작용 가능하다.
      await expect(page.getByTestId("grill-chat-input")).toBeEditable();
    }

    // 1) JSON이 아예 아닌 응답(HTML 에러 페이지 등, 프록시가 502 대신 삼킬 수 있다).
    await page.route(chatUrl, (route) =>
      route.fulfill({ status: 200, contentType: "text/plain", body: "<html>not json at all</html>" }),
    );
    await sendUnderRoute("첫 번째 메시지");
    await expect(assistantBubbles(page).last()).toContainText("AI 응답을 해석하지 못했어요");

    // 2) 필드가 아예 빠진 JSON.
    await page.route(chatUrl, (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) }),
    );
    await sendUnderRoute("두 번째 메시지");
    await expect(assistantBubbles(page).last()).toContainText("AI 응답을 해석하지 못했어요");

    // 3) 타입이 다른 필드 + 배열이어야 할 곳에 문자열 + null.
    await page.route(chatUrl, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ reply: 12345, proposed_requirements: "배열이 아니다", messages: null }),
      }),
    );
    await sendUnderRoute("세 번째 메시지");
    await expect(proposalItems(page)).toHaveCount(0);

    // 4) 터무니없이 긴 문자열 — 표시 상한(4000자)로 잘려야 레이아웃이 무너지지 않는다.
    await page.route(chatUrl, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ reply: "가".repeat(20_000), proposed_requirements: [], messages: [] }),
      }),
    );
    await sendUnderRoute("네 번째 메시지");
    // "-content"는 말풍선 안의 실제 발화만 담는 자식 요소다 — AI 아바타 라벨("AI")
    // 텍스트가 섞이는 바깥 말풍선 testid와 달리, 정확한 길이를 잰다.
    const longText = await assistantBubbles(page).last().locator('[data-testid$="-content"]').textContent();
    expect((longText ?? "").length).toBeLessThanOrEqual(4000);

    // 5) 응답 자체가 오지 않는다 — 연결 실패로 처리되고, 이유가 보이며 재시도할 수 있다.
    await page.route(chatUrl, (route) => route.abort());
    await sendUnderRoute("다섯 번째 메시지");
    await expect(page.getByTestId("grill-chat-error")).toBeVisible();

    expect(pageErrors, `예상치 못한 클라이언트 예외: ${pageErrors.join("\n")}`).toEqual([]);

    // 가로채기를 풀면 대화가 완전히 살아있다 — 정상 응답이 다시 통과한다.
    await page.unroute(chatUrl);
    await page.getByTestId("grill-chat-input").fill("로그인 기능이 필요합니다");
    await page.getByTestId("grill-chat-send").click();
    await expect(page.getByTestId("grill-proposal-0")).toContainText("로그인 기능이 필요합니다");
  });
});
