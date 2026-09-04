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
  test("소스 없이는 제출이 거부되고, 업로드 후에는 저장되며 마감 전까지 몇 번이든 수정할 수 있다", async ({
    page,
  }) => {
    const runId = `${Date.now()}`;
    const contestId = await createContestAsSponsor(page, runId, {
      deadlineAt: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000),
      requirements: [
        { text: "로그인 기능이 동작한다", grade: "required" },
        { text: "다크 모드를 지원한다", grade: "optional" },
      ],
      publish: true,
    });

    const developerSeed = `developer-${runId}`;
    await login(page, developerSeed);
    await verify(page, developerSeed);

    await page.goto(`/console/contests/${contestId}/submit`);

    // 마감까지 남은 시간이 보인다.
    await expect(page.getByTestId("submit-deadline")).toBeVisible();
    await expect(page.getByTestId("submit-deadline")).not.toHaveText("마감되었습니다");

    // 필수 Requirement는 증거가 없으면 시각적으로 구분되고 경고가 뜬다.
    const requiredRows = await page.evaluate(() => {
      const nodes = document.querySelectorAll('[data-testid^="requirement-"][data-unmet-warning]');
      return Array.from(nodes).map((n) => n.getAttribute("data-unmet-warning"));
    });
    expect(requiredRows).toContain("true");

    // 소스 없이 제출하면 거부되고 이유가 보인다 — 네트워크를 타지 않고도 즉시.
    await page.getByTestId("submit-button").click();
    await expect(page.getByTestId("submit-error")).toContainText("소스코드");

    // 소스코드를 업로드한다.
    const sourceContent = `source for ${runId}`;
    await page.getByTestId("source-upload-input").setInputFiles({
      name: "source.zip",
      mimeType: "application/zip",
      buffer: Buffer.from(sourceContent, "utf-8"),
    });
    await expect(page.getByTestId("source-upload-done")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("source-missing-warning")).toHaveCount(0);

    // 필수 Requirement에 증거를 연결한다 — 경고가 사라져야 한다.
    const requiredRow = page.locator('[data-unmet-warning="true"]').first();
    const requiredTestId = await requiredRow.getAttribute("data-testid");
    expect(requiredTestId).toBeTruthy();

    await page.getByTestId(`${requiredTestId}-is-met`).check();
    await page.getByTestId(`${requiredTestId}-add-evidence`).click();
    await page.getByTestId(`${requiredTestId}-evidence-0-value`).fill("src/auth/login.ts");
    await expect(page.getByTestId(`${requiredTestId}-unmet-warning`)).toHaveCount(0);

    // 시연 영상·데모 URL·테스트 계정은 비워둔 채로 제출해도 성공한다.
    await expect(page.getByTestId("demo-url-input")).toHaveValue("");
    await expect(page.getByTestId("test-account-input")).toHaveValue("");

    // 소스가 선정 전까지 Sponsor에게 보이지 않는다는 안내가 있다 — #35의 명시적
    // 인수조건이자 ADR-0014가 Developer에게 하는 약속이다. 노출 여부만 보면
    // 문구가 조용히 다른 말로 바뀌어도 테스트가 못 잡는다(코드리뷰 지적) —
    // 실제 문구까지 확인한다.
    await expect(page.getByTestId("source-privacy-notice")).toContainText(
      "선정(Award) 전까지 Sponsor에게 공개되지 않습니다",
    );

    await page.getByTestId("submit-button").click();
    await expect(page.getByTestId("submit-success")).toBeVisible();

    // 완성도 지표가 채운 만큼(체크리스트 연결 1/2, 권장 항목 0/3) 반영된다.
    const percent = await page.getByTestId("completion-indicator").getAttribute("data-percent");
    expect(Number(percent)).toBeGreaterThan(0);
    expect(Number(percent)).toBeLessThan(100);

    // 새로고침해도 저장된 내용이 그대로 불러와진다 — 그리고 버튼이 "수정"으로 바뀐다.
    await page.reload();
    await expect(page.getByTestId("source-uploaded-key")).toContainText("source");
    await expect(page.getByTestId(`${requiredTestId}-is-met`)).toBeChecked();
    await expect(page.getByTestId("submit-button")).toContainText("수정 사항 저장");

    // 마감 전에는 몇 번이든 수정할 수 있다 — 데모 URL을 채워 다시 저장한다.
    await page.getByTestId("demo-url-input").fill("https://example.com/demo");
    await page.getByTestId("submit-button").click();
    await expect(page.getByTestId("submit-success")).toBeVisible();

    await page.reload();
    await expect(page.getByTestId("demo-url-input")).toHaveValue("https://example.com/demo");
  });

  test("선택 Requirement는 증거가 없어도 미달 경고가 뜨지 않는다", async ({ page }) => {
    const runId = `optional-${Date.now()}`;
    const contestId = await createContestAsSponsor(page, runId, {
      deadlineAt: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000),
      requirements: [{ text: "선택 항목", grade: "optional" }],
      publish: true,
    });

    const developerSeed = `developer-${runId}`;
    await login(page, developerSeed);
    await verify(page, developerSeed);

    await page.goto(`/console/contests/${contestId}/submit`);
    const optionalRow = page.locator('[data-testid^="requirement-"]').first();
    await expect(optionalRow).toHaveAttribute("data-unmet-warning", "false");
  });

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

  test("마감이 지나면 제출·수정이 막힌다", async ({ page }) => {
    const runId = `past-deadline-${Date.now()}`;
    const contestId = await createContestAsSponsor(page, runId, {
      deadlineAt: new Date(Date.now() - 60 * 60 * 1000), // 1시간 전 — 이미 지남
      requirements: [{ text: "이미 지난 마감", grade: "required" }],
      publish: true,
    });

    const developerSeed = `developer-${runId}`;
    await login(page, developerSeed);
    await verify(page, developerSeed);

    await page.goto(`/console/contests/${contestId}/submit`);
    await expect(page.getByTestId("submit-deadline")).toHaveText("마감되었습니다");
    await expect(page.getByTestId("deadline-passed-notice")).toBeVisible();
    await expect(page.getByTestId("submit-button")).toHaveCount(0);
  });
});
