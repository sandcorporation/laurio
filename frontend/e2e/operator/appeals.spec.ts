import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import {
  E2E_OPERATOR_PASSWORD,
  ledgerEntryCount,
  seedE2eOperator,
  seedE2eOperatorAppeal,
  sourceReadingCount,
} from "../lib/seed-operator";
import { establishOperatorSession } from "../lib/session";

// 운영자 앱 08(#66) — 이의 큐와 상세, 그리고 이 티켓의 핵심인 "소스는 접혀
// 있다"(ADR-0022).
//
// 시임 규약(ADR-0021)을 그대로 따른다 — 화면 렌더링·클릭은 `page`로 친다.
// 이의·심판 데이터는 `seed_e2e_operator_appeal` 관리 명령이 멱등하지 않게
// 심으므로(파일 상단 주석), 이 파일의 단언은 항상 시드가 돌려준 구체적인 id·
// 마커·사유 문자열을 대상으로만 이루어진다 — 절대 "목록 전체가 N건"같은 절대
// 개수를 가정하지 않는다.

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
});

test.describe("이의 상세 — 사유와 Score 스냅샷", () => {
});

test.describe("소스는 접혀 있다(#66 핵심, ADR-0022)", () => {
  test("펼치면 소스가 보이고, 그 행위가 Developer 쪽 열람 기록에 실제로 한 건을 남긴다", async ({
    page,
  }) => {
    // 둘은 서로 모르는 시드라 함께 보낸다 — 시험 하나 3초 한도(2026-10-02).
    const [operator, seeded] = await Promise.all([seedE2eOperator(), seedE2eOperatorAppeal()]);

    const before = await sourceReadingCount(seeded.submission_id, seeded.dev_access);

    // 홈을 거치지 않고 이의 화면으로 바로 간다(`establishOperatorSession` 의 `path`).
    await establishOperatorSession(page, operator.username, E2E_OPERATOR_PASSWORD, `/appeals/${seeded.appeal_id}`);
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
    const [operator, seeded] = await Promise.all([seedE2eOperator(), seedE2eOperatorAppeal()]);

    await establishOperatorSession(page, operator.username, E2E_OPERATOR_PASSWORD, `/appeals/${seeded.appeal_id}`);

    // 첫 번째 펼침은 화면이 부르는 바로 그 요청(운영자 BFF 를 거친다)으로 깐다 —
    // 「화면에서 펼치면 한 건이 남는다」는 바로 위 시험이 화면으로 보고, 이 시험이 보는
    // 것은 **같은 이의를 또 펼치면 또 남는다**는 것이다. 예전에는 펼치기·새로고침·
    // 펼치기를 전부 화면으로 해 시험 하나 3초 한도를 넘었다(2026-10-02).
    const first = await page.context().request.post(`/api/backend/operator/appeals/${seeded.appeal_id}/source`, {
      headers: { origin: new URL(page.url()).origin },
    });
    expect(first.status()).toBe(200);
    expect((await first.json()).prompt).toContain(seeded.source_marker);

    const afterFirst = await sourceReadingCount(seeded.submission_id, seeded.dev_access);

    await page.getByTestId("appeal-source-reveal-button").click();
    await expect(page.getByTestId("appeal-source-content")).toContainText(seeded.source_marker);

    await expect
      .poll(() => sourceReadingCount(seeded.submission_id, seeded.dev_access))
      .toBe(afterFirst + 1);
  });
});

/** 「심판 대기」 큐 카드의 현재 표시값을 읽는다 — home.spec.ts의 readQueueValue와
 * 같은 이유(로딩이 끝났다는 것을 자동 대기로 보장하지 않으면 "-count"/"-empty"
 * 어느 쪽도 없는 프레임에서 읽어 통과할 수 없는 단언이 된다). */
async function readPendingAppealsCount(page: Page): Promise<number> {
  const countLocator = page.getByTestId("queue-appeals-pending-count");
  const emptyLocator = page.getByTestId("queue-appeals-pending-empty");
  await expect(countLocator.or(emptyLocator)).toBeVisible();

  if ((await emptyLocator.count()) > 0) return 0;
  const text = await countLocator.textContent();
  return Number.parseInt(text ?? "0", 10);
}

test.describe("이의 심판 — 인용·기각과 감사 추적(#67)", () => {
  test("인용이 만든 정정이 원장에 실제로 반영됐음을 확인한다", async ({ page }) => {
    const [operator, seeded] = await Promise.all([seedE2eOperator(), seedE2eOperatorAppeal()]);

    const before = await ledgerEntryCount(seeded.contest_id);

    await establishOperatorSession(page, operator.username, E2E_OPERATOR_PASSWORD, `/appeals/${seeded.appeal_id}`);
    await page.getByTestId("ruling-note").fill("정정이 원장에 반영되는지 확인.");
    await page.getByTestId("ruling-correction-amount").fill("7777");
    await page.getByTestId("ruling-uphold-button").click();
    await expect(page.getByTestId("appeal-detail-ruling")).toBeVisible();

    expect(await ledgerEntryCount(seeded.contest_id)).toBe(before + 1);
  });

});
