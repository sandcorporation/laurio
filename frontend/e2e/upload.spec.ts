import { expect, test } from "@playwright/test";

// presigned 업로드 (FE-09, #34, ADR-0005).
//
// 핵심 증명은 "파일 바이트가 Next를 거치지 않는다"다 — page.on("request")로 실제
// 네트워크 요청을 관찰해 PUT 요청의 목적지 호스트가 Next(이 baseURL)가 아님을
// 단언한다. dev에서는 MinIO를 상대로 실제 업로드가 끝까지 되는 것까지 증명한다
// (업로드한 내용을 presigned 다운로드 URL로 다시 읽어 비교한다).

function fakeAccessToken(seed: string): string {
  return `${seed}:${seed}@example.test`;
}

async function loginAndVerify(
  page: import("@playwright/test").Page,
  seed: string,
): Promise<number> {
  await page.goto("/login");
  await page.getByTestId("fake-login-seed").fill(seed);
  await page.getByTestId("login-kakao").click();
  await expect(page).toHaveURL(/\/console/);

  const session = await page.evaluate(async () => {
    const res = await fetch("/api/auth/session", { cache: "no-store" });
    return res.json();
  });

  // 본인확인을 마쳐야 Contest를 개최할 수 있다(contests.api.create_contest) —
  // fake 어댑터는 "<실명>|<YYYY-MM-DD>|<ci>|<di>" 형식을 그대로 신뢰한다.
  const verifyStatus = await page.evaluate(async (s) => {
    const res = await fetch("/api/backend/verification/verify", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ verification_token: `업로드테스터|1990-01-01|ci-${s}|di-${s}` }),
    });
    return res.status;
  }, seed);
  expect(verifyStatus).toBe(200);

  return session.id as number;
}

async function createContest(page: import("@playwright/test").Page): Promise<number> {
  const categories = await page.evaluate(async () => {
    const res = await fetch("/api/backend/contests/categories");
    return res.json();
  });
  const deliverableTypes = await page.evaluate(async () => {
    const res = await fetch("/api/backend/contests/deliverable-types");
    return res.json();
  });

  const result = await page.evaluate(
    async ({ categoryId, deliverableTypeId }) => {
      const res = await fetch("/api/backend/contests", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          title: "업로드 데모용 Contest",
          category_id: categoryId,
          deliverable_type_ids: [deliverableTypeId],
          description: "",
          prize: 2_000_000,
          deadline_at: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(),
          requirements: [],
        }),
      });
      return { status: res.status, body: await res.json() };
    },
    { categoryId: categories[0].id, deliverableTypeId: deliverableTypes[0].id },
  );

  expect(result.status, JSON.stringify(result.body)).toBe(200);
  return result.body.id as number;
}

test("presigned 업로드 발급은 프록시를 타지만 실제 PUT은 스토리지로 직행한다", async ({
  page,
  baseURL,
}) => {
  const seed = `upload-${Date.now()}`;
  await loginAndVerify(page, seed);
  const contestId = await createContest(page);

  await page.goto("/console/dev-upload-demo");
  await page.getByTestId("upload-demo-contest-id").fill(String(contestId));

  const fileContent = `hello from ${seed} — presigned upload proof`;

  const observedRequests: { url: string; method: string }[] = [];
  page.on("request", (req) => {
    observedRequests.push({ url: req.url(), method: req.method() });
  });

  const fileChooserInput = page.getByTestId("source-upload-input");
  await fileChooserInput.setInputFiles({
    name: "source.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(fileContent, "utf-8"),
  });

  await expect(page.getByTestId("source-upload-done")).toBeVisible({ timeout: 15_000 });
  const objectKey = await page.getByTestId("upload-demo-object-key").textContent();
  expect(objectKey).toBeTruthy();

  // --- 목적지 호스트 검증 ---------------------------------------------------
  const nextOrigin = new URL(baseURL!).origin;
  const putRequests = observedRequests.filter((r) => r.method === "PUT");
  expect(putRequests.length).toBeGreaterThan(0);
  for (const putRequest of putRequests) {
    const putOrigin = new URL(putRequest.url).origin;
    expect(putOrigin, `PUT이 ${putRequest.url}로 나갔다`).not.toBe(nextOrigin);
  }

  // 발급 요청(POST) 자체는 우리 오리진(BFF 프록시)을 거쳤어야 한다 — 대비되는
  // 증거로 함께 확인한다.
  const issueRequests = observedRequests.filter(
    (r) => r.method === "POST" && r.url.includes("/api/backend/storage/uploads"),
  );
  expect(issueRequests.length).toBeGreaterThan(0);
  for (const issueRequest of issueRequests) {
    expect(new URL(issueRequest.url).origin).toBe(nextOrigin);
  }

  // --- dev에서 MinIO에 실제로 끝까지 업로드됐는지 확인 ------------------------
  const downloaded = await page.evaluate(
    async ({ targetRef, key }) => {
      const res = await fetch("/api/backend/storage/downloads", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ target_ref: targetRef, object_key: key }),
      });
      if (!res.ok) return { ok: false, status: res.status, text: "" };
      const { download_url } = await res.json();
      const fileRes = await fetch(download_url);
      return { ok: fileRes.ok, status: fileRes.status, text: await fileRes.text() };
    },
    { targetRef: `submission:${contestId}:${await getSessionUserId(page)}:source`, key: objectKey },
  );

  expect(downloaded.ok).toBe(true);
  expect(downloaded.text).toBe(fileContent);
});

async function getSessionUserId(page: import("@playwright/test").Page): Promise<number> {
  return page.evaluate(async () => {
    const res = await fetch("/api/auth/session", { cache: "no-store" });
    const body = await res.json();
    return body.id as number;
  });
}

test("업로드 실패는 이유와 함께 보이고 재시도할 수 있다", async ({ page }) => {
  const seed = `upload-fail-${Date.now()}`;
  await loginAndVerify(page, seed);

  await page.goto("/console/dev-upload-demo");
  // 실존하지 않는 Contest — storage.policy가 owner_id를 못 찾아 403으로
  // 거부한다. UploadField가 그 실패를 잡아 이유를 보여주고, 재시도 버튼을
  // 노출해야 한다.
  await page.getByTestId("upload-demo-contest-id").fill("999999999");

  await page.getByTestId("source-upload-input").setInputFiles({
    name: "source.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("won't upload", "utf-8"),
  });

  await expect(page.getByTestId("source-upload-error")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("source-upload-retry")).toBeVisible();
});
