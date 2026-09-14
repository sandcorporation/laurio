import { expect, test } from "@playwright/test";
import { establishDeveloperSession, establishVerification } from "./lib/session";

// 제출 폼 (FE-10, #35, ADR-0014). 이 화면이 Codemit에서 가장 고유한 지점이다.
//
// 지켜야 할 비대칭: 소스코드는 필수(플랫폼의 "강제하지 않고 배지로 신호한다"
// 원칙에서 유일한 예외)이고, 시연 영상·데모 URL·테스트 계정은 비워도 제출이
// 성공한다. 이 스펙이 그 둘을 다른 강도로 검증한다.
//
// Contest를 만드는 사람(Sponsor)과 제출하는 사람(Developer)은 반드시 다른
// 사람이어야 한다 — submissions.api._reject_self_dealing이 같은 CI로 확인되면
// 자전거래로 막는다(REQUEST.md). 그래서 이 스펙의 모든 헬퍼는 Sponsor 로그인과
// Developer 로그인을 뚜렷이 구분한다.

async function login(page: import("@playwright/test").Page, seed: string): Promise<void> {
  await establishDeveloperSession(page, seed);
}

async function verify(page: import("@playwright/test").Page, seed: string): Promise<void> {
  await establishVerification(page, seed);
}

interface CreateContestOptions {
  deadlineAt: Date;
  requirements: { text: string; grade: "required" | "optional" }[];
  publish: boolean;
  // #164 엔트리 포인트 스펙 전용 — `/contests?sort=prize`에서 이 Contest가
  // 항상 1등이도록 다른 스펙들의 통상적인 상금(1~2백만원대)보다 확실히 크게
  // 준다. 목록이 페이지네이션(page_size=20)되므로, 병렬로 도는 다른 스펙이
  // 만든 Contest 수십 건 사이에서 특정 행을 클릭하려면 정렬 1등이 가장
  // 확실하다 — 마감임박순 기본 정렬은 다른 스펙들도 짧은 마감을 흔히 써서
  // 순위가 보장되지 않는다.
  prize?: number;
  title?: string;
}

/** 현재 로그인된 사용자를 Sponsor로 Contest를 만든다. 본인확인이 먼저 돼 있어야 한다. */
async function createContestAsCurrentUser(
  page: import("@playwright/test").Page,
  options: CreateContestOptions,
): Promise<number> {
  const categories = await page.evaluate(async () => {
    const res = await fetch("/api/backend/contests/categories");
    return res.json();
  });
  const deliverableTypes = await page.evaluate(async () => {
    const res = await fetch("/api/backend/contests/deliverable-types");
    return res.json();
  });

  const created = await page.evaluate(
    async ({ categoryId, deliverableTypeId, deadlineAt, requirements, prize, title }) => {
      const res = await fetch("/api/backend/contests", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          title,
          category_id: categoryId,
          deliverable_type_ids: [deliverableTypeId],
          description: "",
          prize,
          deadline_at: deadlineAt,
          requirements,
        }),
      });
      return { status: res.status, body: await res.json() };
    },
    {
      categoryId: categories[0].id,
      deliverableTypeId: deliverableTypes[0].id,
      deadlineAt: options.deadlineAt.toISOString(),
      prize: options.prize ?? 2_000_000,
      title: options.title ?? "[E2E] 제출 폼 데모용 Contest",
      requirements: options.requirements,
    },
  );
  expect(created.status, JSON.stringify(created.body)).toBe(200);
  const contestId = created.body.id as number;

  if (options.publish) {
    const payment = await page.evaluate(async (id) => {
      const res = await fetch("/api/backend/payments", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ contest_id: id }),
      });
      return { status: res.status, body: await res.json() };
    }, contestId);
    expect(payment.status, JSON.stringify(payment.body)).toBe(201);

    const confirm = await page.evaluate(async (orderId) => {
      const res = await fetch(`/api/backend/payments/${orderId}/confirm`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({}),
      });
      return { status: res.status, body: await res.json() };
    }, payment.body.order_id);
    expect(confirm.status, JSON.stringify(confirm.body)).toBe(200);
    expect(confirm.body.status).toBe("paid");
  }

  return contestId;
}

/**
 * 별도의 Sponsor 계정으로 로그인해(본인확인까지 마치고) Contest를 만든 뒤,
 * 페이지 세션을 그대로 둔 채 돌아온다 — 호출부가 이어서 Developer로 로그인해야
 * 제출 폼을 자전거래 없이 테스트할 수 있다.
 */
async function createContestAsSponsor(
  page: import("@playwright/test").Page,
  runId: string,
  options: CreateContestOptions,
): Promise<number> {
  const sponsorSeed = `sponsor-${runId}`;
  await login(page, sponsorSeed);
  await verify(page, sponsorSeed);
  return createContestAsCurrentUser(page, options);
}

test.describe("@exclusive 소스 필수 · Evidence 연결 · 완성도", () => {
  test("본인확인을 마치지 않으면 제출이 막히고 이유와 다음 행동이 안내된다", async ({ page }) => {
    const runId = `unverified-${Date.now()}`;
    const contestId = await createContestAsSponsor(page, runId, {
      deadlineAt: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000),
      requirements: [],
      publish: true,
    });

    const developerSeed = `developer-${runId}`;
    await login(page, developerSeed);
    // verify()를 부르지 않는다 — 본인확인 전 상태를 그대로 유지한다.

    await page.goto(`/console/contests/${contestId}/submit`);
    await expect(page.getByTestId("verification-required")).toBeVisible();
    await expect(page.getByTestId("verification-reason")).toBeVisible();
    await expect(page.getByTestId("verify-now-dev")).toBeVisible();

    // 다음 행동을 실제로 밟으면 막힘이 풀린다(dev fake 본인확인).
    await page.getByTestId("verify-now-dev").click();
    await expect(page.getByTestId("verification-required")).toHaveCount(0, { timeout: 10_000 });
  });

  // #192 — 제출 폼이 종류당 자료 하나만 편집하던 임시 장치(editedAssetIds·
  // untouchedAssets, #190)를 진짜 다중 편집 UI로 갈아끼웠다. 백엔드
  // pytest(`test_editing_keeps_assets_sent_with_their_id_and_drops_the_omitted_ones`)
  // 는 "id를 받으면 병합한다"만 고정한다 — **폼이 실제로 그 id를 실어
  // 보내는가**는 실제 브라우저·실제 저장·실제 재조회를 거쳐야만 보이는
  // 사실이라 여기서만 잡을 수 있다. 새 describe를 만들지 않는다(#192 코드
  // 리뷰 지적) — 이 사실도 위 화면의 유저스토리 한 조각이다.
  test("소스 두 개·저장소·데모 URL을 추가해 저장하면, 다시 열어도 그대로다", async ({ page }) => {
    const runId = `multi-asset-${Date.now()}`;
    const contestId = await createContestAsSponsor(page, runId, {
      deadlineAt: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000),
      requirements: [],
      publish: true,
    });

    const developerSeed = `developer-${runId}`;
    await login(page, developerSeed);
    await verify(page, developerSeed);

    await page.goto(`/console/contests/${contestId}/submit`);
    await expect(page.getByTestId("submit-contest-title")).toBeVisible({ timeout: 10_000 });

    // 소스 두 번째 행을 추가하고 둘 다 업로드한다 — "종류당 하나"였던 옛
    // 제약이 실제로 풀렸는지가 이 스펙의 핵심이다.
    await page.getByTestId("source-asset-0-upload-input").setInputFiles({
      name: "source-a.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(`source A — ${runId}`, "utf-8"),
    });
    await expect(page.getByTestId("source-asset-0-value")).toBeVisible({ timeout: 10_000 });

    await page.getByTestId("source-asset-add").click();
    await page.getByTestId("source-asset-1-upload-input").setInputFiles({
      name: "source-b.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(`source B — ${runId}`, "utf-8"),
    });
    await expect(page.getByTestId("source-asset-1-value")).toBeVisible({ timeout: 10_000 });

    // 저장소 하나(ADR-0027) — 공개 여부는 이 시점에 늘 "확인 중"이다(#193의
    // 스캔이 채우기 전까지).
    await page.getByTestId("repository-asset-add").click();
    await page.getByTestId("repository-asset-0-label").fill("웹 저장소");
    await page.getByTestId("repository-asset-0-value").fill("https://github.com/codemit/e2e-repo");
    await expect(page.getByTestId("repository-checking-badge")).toBeVisible();

    // 데모 URL 하나 — 라벨·테스트 계정까지 함께 저장돼야 한다.
    await page.getByTestId("demo-url-asset-add").click();
    await page.getByTestId("demo-url-asset-0-label").fill("모바일 데모");
    await page.getByTestId("demo-url-asset-0-value").fill("https://demo.codemit.test/e2e");
    await page.getByTestId("demo-url-asset-0-test-account").fill("e2e/e2e1234");

    await page.getByTestId("submit-button").click();
    await expect(page.getByTestId("submit-success")).toBeVisible({ timeout: 10_000 });

    // 다시 연다 — 새로 GET 한 화면이 곧 서버가 실제로 저장한 것이다. id가
    // 실려가지 않았다면(#190 이전 장치가 하던 실수) 여기서 자료가 통째로
    // 사라지거나 다른 종류의 자료를 밀어냈을 것이다.
    await page.reload();
    await expect(page.getByTestId("submit-contest-title")).toBeVisible({ timeout: 10_000 });

    await expect(page.getByTestId("source-asset-0-value")).toBeVisible();
    await expect(page.getByTestId("source-asset-1-value")).toBeVisible();
    await expect(page.getByTestId("source-asset-2-value")).toHaveCount(0);
    await expect(page.getByTestId("repository-asset-0-label")).toHaveValue("웹 저장소");
    await expect(page.getByTestId("repository-asset-0-value")).toHaveValue(
      "https://github.com/codemit/e2e-repo",
    );
    await expect(page.getByTestId("demo-url-asset-0-label")).toHaveValue("모바일 데모");
    await expect(page.getByTestId("demo-url-asset-0-value")).toHaveValue(
      "https://demo.codemit.test/e2e",
    );
    await expect(page.getByTestId("demo-url-asset-0-test-account")).toHaveValue("e2e/e2e1234");
  });
});

// #164 — 공개 상세(`/contests/{id}`)에 제출로 갈 링크가 아예 없던 버그의 회귀
// 스펙. 이 파일의 다른 스펙들은 전부 `page.goto(`/console/contests/${id}/submit`)`
// 로 URL을 직접 쳐서 폼 자체를 검증한다 — 그게 정확히 이 버그를 놓친 방식이다
// (#164 본문: "e2e/submit.spec.ts가 URL을 직접 친다... 사람이 거기 도달할 수
// 있는가는 검증 대상이 아니었다"). 그래서 이 스펙 하나만 `goto`를 목록
// 페이지까지만 쓰고, 그 뒤(상세 → 제출)는 전부 클릭이다 — home.spec.ts의
// "첫 방문자가 클릭만으로 닿는다" 스펙(#93)과 같은 원칙을 여기 적용한다.
test.describe("@exclusive 공개 상세의 제출 진입점 (#164)", () => {
  test("목록에서 클릭해 상세로, 상세에서 클릭해 제출 화면에 도달한다", async ({ page }) => {
    const runId = `entry-${Date.now()}`;
    const title = `[E2E] 제출 진입점 확인용 ${runId}`;
    const contestId = await createContestAsSponsor(page, runId, {
      deadlineAt: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000),
      requirements: [],
      publish: true,
      // 목록은 page_size=20으로 잘린다(#39) — 병렬로 도는 다른 스펙들이 만든
      // Contest 사이에서 이 행이 항상 1페이지에 잡히도록 `sort=prize`
      // 1등이 확실한 상금을 준다(다른 스펙은 전부 1~2백만원대를 쓴다).
      prize: 999_000_000,
      title,
    });

    // Sponsor 본인에게는 이 CTA가 안 보인다(#164 인수조건 — 자기 공모전에는
    // 안 보인다) — 그래서 반드시 다른 사람(Developer)으로 갈아탄 뒤 걷는다.
    const developerSeed = `developer-${runId}`;
    await login(page, developerSeed);
    await verify(page, developerSeed);

    // 여기서부터 goto가 없다 — 목록에서 실제로 렌더된 행을 클릭해 상세로,
    // 상세에서 실제로 렌더된 CTA를 클릭해 제출 화면으로.
    await page.goto("/contests?sort=prize");
    await page.locator(`[data-contest-row="${contestId}"]`).click();
    await expect(page).toHaveURL(new RegExp(`/contests/${contestId}$`));

    await page.getByTestId("submit-cta-link").click();
    await expect(page).toHaveURL(new RegExp(`/console/contests/${contestId}/submit$`));

    // 도착한 화면이 진짜 이 Contest의 제출 폼이다 — 404·에러 화면이 아니라
    // 본인확인을 마친 이 Developer가 실제로 제출을 시작할 수 있는 상태.
    await expect(page.getByTestId("submit-contest-title")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId("submit-contest-title")).toContainText(title);
  });
});
