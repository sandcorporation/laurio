import { expect, test } from "@playwright/test";
import { establishDeveloperSession, establishVerification } from "./lib/session";

// 토스 결제창 — 위젯을 쓸지는 PG 어댑터 모드가 가른다 (#112, #114, spec #110).
//
// payment.spec.ts는 건드리지 않는다 — Fake PG("direct")에서는 결제하기를
// 누르면 지금처럼 곧바로 확정한다는 것이 이 스펙의 제약이다. 이 파일은 그
// 옆에 새로 생기는 두 가지 관찰 가능한 행동을 확인한다:
//
// 1) 실물 어댑터("widget")에서는 결제하기가 토스 SDK로 목적지·파라미터를
//    실어 요청한다 — dev compose 기본값(PAYMENT_ADAPTER_MODE=fake)에서는
//    이 부분이 skip된다(oauth-kakao.spec.ts의 kakaoIsConfigured와 같은
//    관용구 — 설정 여부를 스스로 감지해 갈라 돈다). 벤더에는 실제로
//    나가지 않는다 — 토스 SDK 스크립트 자체를 우리 대역으로 바꿔치기해
//    (js.tosspayments.com에 실제 요청이 나가지 않는다) requestPayment
//    호출의 목적지(clientKey)·파라미터만 관찰한다(카카오 authorize
//    테스트의 관용구 그대로 — 목적지·파라미터를 단언, 실제 왕복은 하지
//    않는다).
// 2) 결제창에서 돌아왔는지 인식하는 것 자체(URL에 paymentKey/code 쿼리
//    파라미터가 있는지)는 checkout_flow와 무관하게 항상 도는 프론트
//    로직이므로, fake 모드에서도 그 쿼리 파라미터를 직접 실어 돌아온
//    상황을 흉내내 확인할 수 있다 — 별도 서버가 필요 없다. 다만 성공
//    경로는 이어서 실제로 confirm을 부르므로(paymentKey → 백엔드 →
//    어댑터), 그 확정까지 확인하는 테스트는 fake PG 환경으로 스스로
//    한정한다 — 실물 어댑터에서 지어낸 paymentKey로 confirm을 부르면
//    벤더에 실제 네트워크 요청이 나간다(금지). 실패 경로는 confirm을
//    아예 부르지 않으므로 이 제약이 없다.

async function login(page: import("@playwright/test").Page, seed: string): Promise<void> {
  await establishDeveloperSession(page, seed);
}

async function verify(page: import("@playwright/test").Page, seed: string): Promise<void> {
  await establishVerification(page, seed);
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

/** payment.spec.ts의 createDraftViaForm과 같은 헬퍼 — 화면 URL에는 id가
 * 없다(grill.spec.ts부터 반복되는 관용구). */
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

  await page.getByTestId("grill-brief-title").fill(`[E2E] 토스 결제 테스트 ${runId}`);
  await page.getByTestId("grill-brief-category").selectOption(String(categoryId));
  await page.getByTestId(`grill-brief-deliverable-type-${deliverableTypeId}-checkbox`).check();
  await page.getByTestId("grill-brief-prize").fill(String(prize));
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

/** 결제 화면으로 이동해 initiate_payment 응답을 그대로 돌려준다 — 서버가
 * 지금 이 Contest에 대해 "direct"(fake PG)와 "widget"(실물 어댑터) 중
 * 무엇을 요구하는지는 이 응답의 checkout_flow로만 알 수 있다. */
async function gotoPaymentAndReadResponse(
  page: import("@playwright/test").Page,
  contestId: number,
  extraSearch = "",
): Promise<{ order_id: string; total_amount: number; checkout_flow: string }> {
  const [response] = await Promise.all([
    page.waitForResponse(
      (res) => res.url().endsWith("/api/backend/payments") && res.request().method() === "POST",
    ),
    page.goto(`/console/contests/${contestId}/payment${extraSearch}`),
  ]);
  return response.json();
}

// 토스 SDK 스크립트를 대신한다 — window.TossPayments.payment(...).requestPayment(...)
// 호출에 실린 값을 전역에 기록만 하고, 실제 벤더 도메인으로는 절대 나가지
// 않는다(현재 페이지에 머문다).
const FAKE_TOSS_SDK_SOURCE = `
window.TossPayments = function(clientKey) {
  return {
    payment: function(opts) {
      return {
        requestPayment: function(params) {
          window.__codemitTossRequestPayment = {
            clientKey: clientKey,
            customerKey: opts.customerKey,
            params: params,
          };
          return Promise.resolve();
        },
      };
    },
  };
};
`;

test.describe("실물 어댑터 — 결제하기가 토스 SDK로 목적지·파라미터를 실어 요청한다", () => {
});

test.describe("결제창에서 돌아온 뒤 — URL 파라미터 인식 자체는 checkout_flow와 무관하다", () => {
  test("돌아온 paymentKey의 orderId가 현재 결제 건과 다르면 확정을 시도하지 않고 거부한다", async ({
    page,
  }) => {
    // 세션이 만료돼 /login을 왕복하는 사이 이전 결제(A)가 실패 웹훅으로
    // 종결되고 loadAll이 새 결제(B)를 만들었을 수 있다 — 그 사이 A의
    // paymentKey가 그대로 B의 화면으로 돌아온 상황을 흉내낸다(#112 코드리뷰
    // 지적 2). orderId가 지금 화면이 들고 있는 결제 건과 다르므로 confirm을
    // 아예 부르지 않고 거부해야 한다.
    const runId = `${Date.now()}`;
    await login(page, `pay-toss-mismatch-${runId}`);
    await verify(page, `pay-toss-mismatch-${runId}`);
    const contestId = await createDraftViaForm(page, runId, 5_000_000);

    const payment = await gotoPaymentAndReadResponse(page, contestId);
    const mismatchedOrderId = "00000000-0000-0000-0000-000000000000";
    expect(mismatchedOrderId).not.toBe(payment.order_id);

    await page.goto(
      `/console/contests/${contestId}/payment` +
        `?paymentKey=stale-key-${runId}&orderId=${mismatchedOrderId}&amount=${payment.total_amount}`,
    );

    await expect(page.getByTestId("payment-failed")).toBeVisible();
    await expect(page.getByTestId("payment-failed")).toContainText("일치하지 않습니다");

    // confirm이 아예 호출되지 않았다 — Contest는 여전히 draft다. 이 fetch는
    // 아직 로그인된 브라우저 세션(소유자)에서 나가므로 draft라도 200으로
    // 보인다(get_contest의 소유자 예외) — 그래서 상태 문자열 자체를 본다.
    const contestStatus = await page.evaluate(async (id) => {
      const res = await fetch(`/api/backend/contests/${id}`);
      return (await res.json()).status as string;
    }, contestId);
    expect(contestStatus).toBe("draft");
  });
});
