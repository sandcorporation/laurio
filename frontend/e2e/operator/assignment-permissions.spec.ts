import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import {
  E2E_OPERATOR_PASSWORD,
  seedE2eAssignmentPermissionSponsor,
  seedE2eOperator,
} from "../lib/seed-operator";
import { establishOperatorSession } from "../lib/session";

// 운영자 앱 — 과제 개최 자격 관리(#206, ADR-0028/0029).
//
// 과제(Assignment)에는 결제가 없어 비용이 스스로 제어되지 않는다 — 개최비가
// 서 있던 자리를 운영자가 여는 문이 대신한다. 이 스펙 하나가 남는 이유는
// CLAUDE.md의 「남길 것」 기준이다: 전용 위험 스펙(SSR·미들웨어 가드)이 이미
// 다른 곳에서 한 번 보고, 여기서는 새 프록시 라우트가 실제로 허용목록을
// 통과하는지(위험 3)를 이 흐름이 지나가며 함께 덮는다 — 그리고 "앱마다 유저
// 스토리 한 벌"에서 운영자 앱 몫이 이것이다: 자격을 주고, 그 사실이 이력에
// 남고, 회수하면 목록에서 빠진다.
//
// 시임 규약(ADR-0021)을 그대로 따른다 — 렌더링·클릭은 `page`로 친다. 부여·
// 회수는 효과(목록에 나타남/사라짐, 이력 행)로 증명한다.

async function loginAndExpectHome(page: Page, username: string, password = E2E_OPERATOR_PASSWORD): Promise<void> {
  await establishOperatorSession(page, username, password);
  await expect(page.getByTestId("operator-home-heading")).toBeVisible();
}

test.describe("자격을 주고, 이력에 남고, 회수하면 목록에서 빠진다(#206)", () => {
  test("상위 등급 운영자가 자격을 부여·회수하는 한 벌", async ({ page }) => {
    const root = await seedE2eOperator({
      username: `e2e-op-asgnperm-${Date.now()}`,
      superuser: true,
    });
    const sponsor = await seedE2eAssignmentPermissionSponsor();

    await loginAndExpectHome(page, root.username, E2E_OPERATOR_PASSWORD);

    // 홈에서 실제로 눌러 들어간다 — URL을 직접 치지 않는다(#69가 남긴 함정:
    // 링크 없는 화면을 e2e가 놓친 적이 있다).
    await page.getByTestId("assignment-permissions-nav-link").click();
    await expect(page.getByTestId("assignment-permissions-heading")).toBeVisible();

    // 부여 전에는 이 Sponsor가 보유자 목록에 없다.
    const holdersTableOrEmpty = page.getByTestId(/assignment-permissions-(table|empty)/);
    await expect(holdersTableOrEmpty.first()).toBeVisible();

    // 부여 — 이유를 함께 남긴다(정책·산출물 종류 화면과 같은 규율).
    await page.getByTestId("grant-assignment-permission-username").fill(sponsor.username);
    await page
      .getByTestId("grant-assignment-permission-reason")
      .fill("e2e — 수업 개설 승인");
    await page.getByTestId("grant-assignment-permission-submit").click();

    // 효과 1 — 목록에 나타난다.
    await expect(page.getByTestId("assignment-permissions-table")).toBeVisible();
    const row = page
      .getByTestId("assignment-permissions-table")
      .locator("tr", { hasText: sponsor.username });
    await expect(row).toBeVisible();

    // 효과 2 — 변경 이력에 「부여」로 남는다.
    const historyTable = page.getByTestId("assignment-permission-history-table");
    await expect(historyTable).toBeVisible();
    const grantedHistoryRow = historyTable.locator("tr", { hasText: sponsor.username }).filter({
      hasText: "부여",
    });
    await expect(grantedHistoryRow).toBeVisible();
    await expect(grantedHistoryRow).toContainText("e2e — 수업 개설 승인");

    // 회수 — 이미 열린 과제는 영향받지 않는다는 사실을 화면이 말한다(AC).
    await row.getByRole("button", { name: "자격 회수" }).click();
    await expect(row.getByText("이미 열린 과제는 끝까지 그대로 돕니다")).toBeVisible();
    await row.locator('[data-testid$="-revoke-reason"]').fill("e2e — 회수 사유");
    await row.locator('[data-testid$="-revoke-confirm"]').click();

    // 효과 3 — 목록에서 사라진다.
    await expect(
      page.getByTestId("assignment-permissions-table").locator("tr", { hasText: sponsor.username }),
    ).toHaveCount(0);

    // 효과 4 — 이력에는 「회수」가 추가로 남고, 「부여」 행은 지워지지 않는다.
    const revokedHistoryRow = historyTable.locator("tr", { hasText: sponsor.username }).filter({
      hasText: "회수",
    });
    await expect(revokedHistoryRow).toBeVisible();
    await expect(grantedHistoryRow).toBeVisible();
  });
});
