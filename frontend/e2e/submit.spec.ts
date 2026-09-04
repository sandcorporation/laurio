import { expect, test } from "@playwright/test";
import { establishDeveloperSession, establishVerification } from "./lib/session";

// 제출 폼 (FE-10, #35, ADR-0014). 이 화면이 Laurio에서 가장 고유한 지점이다.
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
    async ({ categoryId, deliverableTypeId, deadlineAt, requirements }) => {
      const res = await fetch("/api/backend/contests", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          title: "[E2E] 제출 폼 데모용 Contest",
          category_id: categoryId,
          deliverable_type_ids: [deliverableTypeId],
          description: "",
          prize: 2_000_000,
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

});
