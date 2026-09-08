import { expect, test } from "@playwright/test";
import { establishDeveloperSession, establishVerification, publicOrigin } from "./lib/session";

// ContestImage — 공개 버킷과 CDN (#234, ADR-0032).
//
// 이 스펙 하나가 CLAUDE.md 「남길 것」의 두 위험을 함께 진다:
//
// 1. **공개 페이지가 실제로 서버 렌더링되는가** — 이미지가 붙은 Contest 상세를
//    JS 없이 열었을 때 그 이미지 태그가 HTML에 있는가.
// 2. **공개 버킷에 anonymous read가 실제로 걸렸는가** — 이것이 어느 백엔드
//    테스트도 볼 수 없는 유일한 사실이다(spec #225 Testing Decisions). 백엔드는
//    CDN 주소를 조립해 돌려줄 뿐이고 FakeStorageAdapter는 버킷 정책을 모른다.
//    로그아웃 상태의 브라우저로 이미지가 실제로 로드되는지를 본다 — 버킷이
//    private이면 그 자리에서 깨진다.
//
// 이미지를 붙이는 것 자체(업로드 URL 발급·presigned POST·행 등록·순서·제거)는
// backend/tests/test_contest_images.py가 마운트된 HTTP로 이미 고정한다 — 여기서
// 다시 그 경로 하나하나를 단언하지 않는다. 이 스펙은 그 뒤에 남는, 화면으로만
// 확인되는 두 가지만 본다.

// 1x1 투명 PNG — presigned POST 정책의 image/png 허용 범위 안에서 가장 작은 유효한 이미지.
const ONE_PIXEL_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
  "base64",
);

async function findIdByName(
  request: import("@playwright/test").APIRequestContext,
  path: string,
  name: string,
): Promise<number> {
  const res = await request.get(path);
  const list = (await res.json()) as { id: number; name: string }[];
  const found = list.find((item) => item.name === name);
  expect(found, `"${name}"을(를) ${path}에서 찾지 못했다`).toBeTruthy();
  return (found as { id: number }).id;
}

test("개최자가 올린 이미지가 공개 상세에 서버 렌더링되고, 로그아웃 상태에서도 실제로 로드된다", async ({
  page,
  request,
}) => {
  // **인증 구역 호출은 `page.context().request` 로 한다** — 독립 `request` 픽스처가
  // 아니라. 그 픽스처는 브라우저 컨텍스트와 별개라 (1) 로그인 쿠키를 공유하지 않아
  // 401 이 나고, (2) Origin 을 자동으로 싣지 않아 BFF 프록시가 「브라우저가 보낸 게
  // 아닌 요청」으로 보고 403 으로 막는다(ADR-0016 — `auth.spec.ts` 가 그 fail-closed
  // 동작을 일부러 단언한다). 브라우저 컨텍스트의 request 는 둘 다 공짜로 해결한다 —
  // `e2e/lib/session.ts` 가 이미 그렇게 한다.
  //
  // 스토리지로 직행하는 presigned POST 만 독립 `request` 를 쓴다: 그건 프록시를
  // 거치지 않고 MinIO 를 직접 치므로 우리 쿠키도 오리진도 실을 이유가 없다.
  //
  // **Origin 은 그래도 손으로 붙인다.** 컨텍스트에 묶인 request 도 브라우저의 fetch 가
  // 아니라 API 클라이언트라 Origin 을 자동으로 싣지 않는다 — 쿠키만 공유한다.
  // `publicOrigin()` 을 쓰는 이유는 그 함수 위 주석에 있다(끝의 슬래시 하나로 전부
  // 403 이 된다).
  const api = page.context().request;
  const sameOrigin = { origin: publicOrigin() };
  const runId = `${Date.now()}`;
  await establishDeveloperSession(page, `img-${runId}`);
  await establishVerification(page, `img-${runId}`);

  const categoryId = await findIdByName(api, "/api/backend/contests/categories", "게임");
  const deliverableTypeId = await findIdByName(
    api,
    "/api/backend/contests/deliverable-types",
    "웹 서비스",
  );

  // draft 개최.
  const created = await api.post("/api/backend/contests", {
    headers: sameOrigin,
    data: {
      title: `[E2E] 이미지 공개 검증 ${runId}`,
      category_id: categoryId,
      deliverable_type_ids: [deliverableTypeId],
      description: "",
      prize: 1_000_000,
      deadline_at: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString(),
    },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const contestId = (await created.json()).id as number;

  // presigned POST 발급.
  const issued = await api.post(`/api/backend/contests/${contestId}/images/upload-url`, {
    headers: sameOrigin,
    data: { content_type: "image/png" },
  });
  expect(issued.ok(), await issued.text()).toBeTruthy();
  const uploadUrl = (await issued.json()) as {
    object_key: string;
    upload_url: string;
    fields: Record<string, string>;
  };

  // 실제 바이트를 공개 이미지 버킷에 올린다 — presigned POST이므로 서명된
  // 필드를 그대로 실어야 한다(fields가 file보다 먼저 와야 하는 것은
  // FormData 자체의 규약이라 Playwright의 multipart 옵션이 그대로 지킨다).
  const uploaded = await request.post(uploadUrl.upload_url, {
    multipart: {
      ...uploadUrl.fields,
      file: { name: "reference.png", mimeType: "image/png", buffer: ONE_PIXEL_PNG },
    },
  });
  expect(uploaded.ok(), `스토리지 업로드 실패: ${uploaded.status()} ${await uploaded.text()}`).toBeTruthy();

  // 업로드 완료를 Contest에 등록.
  const registered = await api.post(`/api/backend/contests/${contestId}/images`, {
    headers: sameOrigin,
    data: { object_key: uploadUrl.object_key },
  });
  expect(registered.ok(), await registered.text()).toBeTruthy();
  const image = (await registered.json()) as { url: string };

  // 결제를 완료해 공개한다(Fake PG, #86) — 이미지도 "결제가 닫는 조건"의
  // 일부이므로 공개 뒤에도 그대로 보여야 한다는 것까지 함께 확인한다.
  const payment = await api.post("/api/backend/payments", {
    headers: sameOrigin,
    data: { contest_id: contestId },
  });
  expect(payment.ok(), await payment.text()).toBeTruthy();
  const orderId = (await payment.json()).order_id as string;
  const confirmed = await api.post(`/api/backend/payments/${orderId}/confirm`, {
    headers: sameOrigin,
    data: { payment_key: `e2e-fake-${runId}` },
  });
  expect(confirmed.ok(), await confirmed.text()).toBeTruthy();

  // --- 1. 서버 렌더링: JS 없이 받은 HTML에 이미지 태그가 있다 ---
  const jsOffContext = await page.context().browser()!.newContext({ javaScriptEnabled: false });
  try {
    const jsOffPage = await jsOffContext.newPage();
    await jsOffPage.goto(`/contests/${contestId}`);
    const html = await jsOffPage.content();
    expect(html).toContain(image.url);
  } finally {
    await jsOffContext.close();
  }

  // --- 2. 공개 버킷에 anonymous read가 실제로 걸려 있다 ---
  // 완전히 새 컨텍스트(로그인 쿠키 없음)로, 이미지 URL을 직접 연다 — 버킷이
  // private이면 여기서 403/AccessDenied로 깨진다.
  const anonymousContext = await page.context().browser()!.newContext();
  try {
    const anonymousPage = await anonymousContext.newPage();
    await anonymousPage.goto(`/contests/${contestId}`);
    const imageResponse = await anonymousPage.waitForResponse(
      (res) => res.url() === image.url,
      { timeout: 15_000 },
    ).catch(() => null);

    // 브라우저가 그 이미지를 이미 로드해 캐시했을 수도 있으므로(waitForResponse가
    // 이벤트를 놓치는 경우), 직접 한 번 더 요청해 상태 코드로 확정한다 — 이
    // 요청도 같은 컨텍스트(로그인 쿠키 없음)에서 나간다.
    const direct = await anonymousContext.request.get(image.url);
    expect(direct.status(), "공개 이미지 버킷에서 anonymous read가 거부됐다").toBe(200);
    expect(direct.headers()["content-type"]).toContain("image/png");

    if (imageResponse) {
      expect(imageResponse.status()).toBe(200);
    }
  } finally {
    await anonymousContext.close();
  }
});
