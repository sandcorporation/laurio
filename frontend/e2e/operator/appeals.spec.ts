import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import {
  E2E_OPERATOR_PASSWORD,
  seedE2eOperator,
  seedE2eOperatorAppeal,
  sourceReadingCount,
} from "../lib/seed-operator";

// 운영자 앱 08(#66) — 이의 큐와 상세, 그리고 이 티켓의 핵심인 "소스는 접혀
// 있다"(ADR-0022).
//
// 시임 규약(ADR-0021)을 그대로 따른다 — 화면 렌더링·클릭은 `page`로 친다.
// 이의·심판 데이터는 `seed_e2e_operator_appeal` 관리 명령이 멱등하지 않게
// 심으므로(파일 상단 주석), 이 파일의 단언은 항상 시드가 돌려준 구체적인 id·
// 마커·사유 문자열을 대상으로만 이루어진다 — 절대 "목록 전체가 N건"같은 절대
// 개수를 가정하지 않는다.

async function loginAsOperator(page: Page, username: string): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("login-username").fill(username);
  await page.getByTestId("login-password").fill(E2E_OPERATOR_PASSWORD);
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("operator-home-heading")).toBeVisible();
}

/** 목록 로딩이 끝나길 기다린다 — 셋 중 하나(목록·빈 상태·실패)가 뜰 때까지.
 * home.spec.ts의 readQueueValue와 같은 이유: locator.all()/count()는 자동
 * 대기하지 않으므로, 로딩이 끝났다는 것을 먼저 보장하지 않고 행을 세면
 * 아무것도 증명하지 못한 채 통과할 수 있다. */
async function waitForAppealsListSettled(page: Page): Promise<void> {
  await expect(
    page
      .getByTestId("appeals-list")
      .or(page.getByTestId("appeals-list-empty"))
      .or(page.getByTestId("appeals-list-error")),
  ).toBeVisible();
}

test.describe("이의 큐 — 기본은 심판 대기, 필터로 그 외도 본다", () => {
  test("기본(쿼리 없음)은 심판 대기 건만 보여준다 — 인용된 건은 안 보인다", async ({
    page,
  }) => {
    const operator = seedE2eOperator({ username: `e2e-op-appeals-default-${Date.now()}` });
    const pending = seedE2eOperatorAppeal();
    const upheld = seedE2eOperatorAppeal("uphold");

    await loginAsOperator(page, operator.username);
    await page.goto("/appeals");
    await waitForAppealsListSettled(page);

    await expect(page.getByTestId(`appeal-row-${pending.appeal_id}`)).toBeVisible();
    await expect(page.getByTestId(`appeal-row-${upheld.appeal_id}`)).toHaveCount(0);
  });

  test("상태 필터로 인용·기각된 건도 볼 수 있다", async ({ page }) => {
    const operator = seedE2eOperator({ username: `e2e-op-appeals-filter-${Date.now()}` });
    const rejected = seedE2eOperatorAppeal("reject");

    await loginAsOperator(page, operator.username);
    await page.goto("/appeals");
    await waitForAppealsListSettled(page);
    // 기본(pending) 화면에는 기각된 건이 없다.
    await expect(page.getByTestId(`appeal-row-${rejected.appeal_id}`)).toHaveCount(0);

    await page.getByTestId("appeals-status-filter").selectOption("rejected");
    await waitForAppealsListSettled(page);
    await expect(page.getByTestId(`appeal-row-${rejected.appeal_id}`)).toBeVisible();
  });

  test("각 행이 어느 Submission인지와 제기 시각을 보여준다", async ({ page }) => {
    const operator = seedE2eOperator({ username: `e2e-op-appeals-row-${Date.now()}` });
    const seeded = seedE2eOperatorAppeal();

    await loginAsOperator(page, operator.username);
    await page.goto("/appeals");
    await waitForAppealsListSettled(page);

    const row = page.getByTestId(`appeal-row-${seeded.appeal_id}`);
    await expect(row).toBeVisible();
    await expect(page.getByTestId(`appeal-row-${seeded.appeal_id}-submission`)).toContainText(
      `Submission #${seeded.submission_id}`,
    );
    const createdAtText = await page
      .getByTestId(`appeal-row-${seeded.appeal_id}-created-at`)
      .textContent();
    expect(createdAtText?.trim()).toBeTruthy();
  });

  test("목록이 비어 있으면 빈 목록이라고 명시적으로 말한다", async ({ page }) => {
    const operator = seedE2eOperator({ username: `e2e-op-appeals-empty-${Date.now()}` });
    await loginAsOperator(page, operator.username);

    // 실제 DB에 이미 pending 이의가 있을 수 있으므로(다른 테스트가 같은 실행
    // 안에서 심었을 수 있다) 이 목록 조회만 좁혀 결정적으로 빈 배열을 흉내낸다
    // (home.spec.ts의 조회 실패 시뮬레이션과 같은 원칙 — 순수 프론트 렌더링
    // 분기 하나만 겨냥한다).
    await page.route("**/api/backend/operator/appeals*", (route) =>
      route.fulfill({ status: 200, body: "[]", headers: { "content-type": "application/json" } }),
    );

    await page.goto("/appeals");
    await expect(page.getByTestId("appeals-list-empty")).toContainText("표시할 이의가 없습니다");
    await expect(page.getByTestId("appeals-list-error")).toHaveCount(0);
    await expect(page.getByTestId("appeals-list")).toHaveCount(0);
  });

  test("조회 실패는 실패라고 말한다 — 빈 목록처럼 보이지 않는다", async ({ page }) => {
    const operator = seedE2eOperator({ username: `e2e-op-appeals-fail-${Date.now()}` });
    await loginAsOperator(page, operator.username);

    await page.route("**/api/backend/operator/appeals*", (route) =>
      route.fulfill({ status: 500, body: JSON.stringify({ detail: "boom" }) }),
    );

    await page.goto("/appeals");
    await expect(page.getByTestId("appeals-list-error")).toContainText("불러오지 못했습니다");
    await expect(page.getByTestId("appeals-list-empty")).toHaveCount(0);
    await expect(page.getByTestId("appeals-list")).toHaveCount(0);
  });
});

test.describe("이의 상세 — 사유와 Score 스냅샷", () => {
  test("이의 사유와 Score 스냅샷(점수·모델버전·근거·채점 시각)이 보인다", async ({
    page,
  }) => {
    const operator = seedE2eOperator({ username: `e2e-op-appeals-detail-${Date.now()}` });
    const seeded = seedE2eOperatorAppeal();

    await loginAsOperator(page, operator.username);
    await page.goto(`/appeals/${seeded.appeal_id}`);

    await expect(page.getByTestId("appeal-detail-reason")).toContainText(seeded.reason);
    await expect(page.getByTestId("appeal-detail-score-percentage")).toBeVisible();
    await expect(page.getByTestId("appeal-detail-score-model-version")).toBeVisible();
    await expect(page.getByTestId("appeal-detail-score-reasoning")).toBeVisible();
    await expect(page.getByTestId("appeal-detail-score-created-at")).toBeVisible();
  });

  test("존재하지 않는 이의를 열면 없다고 말한다 — 빈 상세가 그려지지 않는다", async ({
    page,
  }) => {
    const operator = seedE2eOperator({ username: `e2e-op-appeals-404-${Date.now()}` });
    await loginAsOperator(page, operator.username);

    await page.goto("/appeals/999999999");

    await expect(page.getByTestId("appeal-detail-not-found")).toContainText(
      "이의를 찾을 수 없습니다",
    );
    await expect(page.getByTestId("appeal-detail-reason")).toHaveCount(0);
    await expect(page.getByTestId("appeal-detail-score")).toHaveCount(0);
  });

  test("이미 심판된 이의는 폼 없이 결과를 읽기 전용으로 보여준다", async ({ page }) => {
    const operator = seedE2eOperator({ username: `e2e-op-appeals-ruled-${Date.now()}` });
    const seeded = seedE2eOperatorAppeal("uphold");
    const ruling = seeded.ruling;
    if (!ruling) throw new Error("uphold로 심은 이의에 ruling이 없다 — 시드 자체가 깨졌다.");

    await loginAsOperator(page, operator.username);
    await page.goto(`/appeals/${seeded.appeal_id}`);

    await expect(page.getByTestId("appeal-detail-ruling")).toBeVisible();
    await expect(page.getByTestId("appeal-detail-ruling-ruled-by")).toContainText(
      ruling.ruled_by_username,
    );
    await expect(page.getByTestId("appeal-detail-ruling-note")).toContainText(ruling.note);
    await expect(page.getByTestId("appeal-detail-ruling-correction-amount")).toContainText(
      String(ruling.correction_amount),
    );

    // 심판 폼 요소가 전혀 없다 — 인용/기각 버튼도, 정정 금액 입력도.
    await expect(page.locator("form")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /인용|기각/ })).toHaveCount(0);
  });
});

test.describe("소스는 접혀 있다(#66 핵심, ADR-0022)", () => {
  test("펼치기 전에는 화면 어디에도 소스 내용이 없다 — 아직 가져오지 않은 상태다", async ({
    page,
  }) => {
    const operator = seedE2eOperator({ username: `e2e-op-appeals-collapsed-${Date.now()}` });
    const seeded = seedE2eOperatorAppeal();

    await loginAsOperator(page, operator.username);
    await page.goto(`/appeals/${seeded.appeal_id}`);
    await expect(page.getByTestId("appeal-detail-reason")).toBeVisible();

    // HTML 본문에 display:none으로 숨겨둔 것이 아니라 애초에 없어야 한다 —
    // body 전체 텍스트에 마커가 없는지로 확인한다(hidden 요소의 textContent도
    // 포함하는 검사라 "숨기기만 한" 구현은 여기서 걸린다).
    await expect(page.locator("body")).not.toContainText(seeded.source_marker);
    await expect(page.getByTestId("appeal-source-content")).toHaveCount(0);

    // 펼치기 전에 "펼치면 기록된다"는 경고가 이미 화면에 있다.
    await expect(page.getByTestId("appeal-source-warning")).toBeVisible();
    await expect(page.getByTestId("appeal-source-reveal-button")).toBeVisible();
  });

  test("펼치면 소스가 보이고, 그 행위가 Developer 쪽 열람 기록에 실제로 한 건을 남긴다", async ({
    page,
  }) => {
    const operator = seedE2eOperator({ username: `e2e-op-appeals-reveal-${Date.now()}` });
    const seeded = seedE2eOperatorAppeal();

    const before = await sourceReadingCount(seeded.submission_id, seeded.dev_access);

    await loginAsOperator(page, operator.username);
    await page.goto(`/appeals/${seeded.appeal_id}`);
    await expect(page.getByTestId("appeal-source-warning")).toBeVisible();

    await page.getByTestId("appeal-source-reveal-button").click();

    await expect(page.getByTestId("appeal-source-content")).toContainText(seeded.source_marker);

    // 티켓 03의 표면(GET /submissions/{id}/source-readings)에서 정확히 1건이
    // 늘어난 것까지 확인한다 — 펼침과 기록이 같은 요청에서 함께 일어난다는
    // ADR-0022의 요구를 백엔드가 아니라 이 화면의 행위를 통해 검증한다.
    await expect
      .poll(() => sourceReadingCount(seeded.submission_id, seeded.dev_access))
      .toBe(before + 1);
  });

  test("같은 이의를 다시 펼치면 열람 기록이 하나 더 쌓인다 — 사건이지 상태가 아니다", async ({
    page,
  }) => {
    const operator = seedE2eOperator({ username: `e2e-op-appeals-reveal-twice-${Date.now()}` });
    const seeded = seedE2eOperatorAppeal();

    await loginAsOperator(page, operator.username);
    await page.goto(`/appeals/${seeded.appeal_id}`);
    await page.getByTestId("appeal-source-reveal-button").click();
    await expect(page.getByTestId("appeal-source-content")).toContainText(seeded.source_marker);

    const afterFirst = await sourceReadingCount(seeded.submission_id, seeded.dev_access);

    await page.reload();
    await page.getByTestId("appeal-source-reveal-button").click();
    await expect(page.getByTestId("appeal-source-content")).toContainText(seeded.source_marker);

    await expect
      .poll(() => sourceReadingCount(seeded.submission_id, seeded.dev_access))
      .toBe(afterFirst + 1);
  });
});
