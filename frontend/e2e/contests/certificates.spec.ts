// 개최자 「상장」 화면 (#1129, 스펙 #1071) — 마감 뒤 제출자를 골라 칸을 채우고 발급하면,
// 새로고침 뒤에도 목록에 남고, 취소하거나 고쳐 다시 발급할 수 있다. 칸의 규칙(길이·날짜·
// 금칙어·발급 수 한도)과 PDF 내용은 backend/tests/integration/test_certificate_issue.py 가 본다 —
// 여기서는 화면이 실제 스택에 닿는지만 본다.
import { expect, test, type Page } from "@playwright/test";

import { seedE2eContests } from "../lib/seed";
import { establishDeveloperSession } from "../lib/session";

// 준비는 화면이 아니라 API 로 — 상장 한 장을 미리 발급해 둔다(렌더가 있어 한 번에 1초 안팎).
async function issueViaApi(page: Page, id: number, submissionId: number): Promise<void> {
  const status = await page.evaluate(
    async ({ url, submissionId }) => {
      const board = await (await fetch(url)).json();
      const max: string = board.defaults.award_date_max;
      const today = new Date().toISOString().slice(0, 10);
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          items: [
            {
              submission_id: submissionId,
              text: {
                award_name: "우수상",
                recipient_name: "홍길동",
                body: "",
                giver_name: board.defaults.giver_name,
                giver_title: "",
                award_date: max < today ? max : today,
              },
            },
          ],
        }),
      });
      return response.status;
    },
    { url: `/api/backend/contests/${id}/certificates`, submissionId },
  );
  expect(status).toBe(201);
}

async function openBoard(page: Page) {
  const seeded = await seedE2eContests();
  await establishDeveloperSession(page, seeded.judging.sponsor_login_seed);
  const { id, submissions } = seeded.judging;
  await page.goto(`/console/contests/${id}/certificates`);
  await expect(page.getByTestId("certificates-contest-title")).toBeVisible();
  return { id, submissionId: submissions[0].id };
}

test("제출자를 골라 상장을 발급하면 새로고침 뒤에도 목록에 있다", async ({ page }) => {
  const { submissionId } = await openBoard(page);

  await page.getByTestId(`certificates-pick-${submissionId}`).check();
  await page.getByTestId(`certificates-draft-${submissionId}-award-name`).fill("최우수상");
  await page.getByTestId("certificates-issue").click();
  // 되돌릴 수 없다는 경고가 먼저 뜬다 — 확인 전에는 발급되지 않는다.
  await expect(page.getByTestId("certificates-confirm")).toContainText("고칠 수 없고");
  await expect(page.getByTestId("certificates-issued-empty")).toBeVisible();
  await page.getByTestId("certificates-confirm-issue").click();

  const row = page.locator('[data-testid^="certificates-row-"]');
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("최우수상");
  await expect(row).toHaveAttribute("data-status", "valid");

  await page.reload();
  await expect(row).toHaveCount(1);
  await expect(row).toHaveAttribute("data-status", "valid");
  // 발급된 제출자는 더 고를 수 없다.
  await expect(page.getByTestId(`certificates-pick-${submissionId}`)).toBeDisabled();
});

test("발급한 상장을 취소한다 — 경고를 거쳐 「취소됨」이 되고 그 사람은 다시 고를 수 있다", async ({ page }) => {
  const { id, submissionId } = await openBoard(page);
  await issueViaApi(page, id, submissionId);
  await page.reload();

  const row = page.locator('[data-testid^="certificates-row-"]');
  await expect(row).toHaveAttribute("data-status", "valid");
  await row.getByRole("button", { name: "취소", exact: true }).click();
  await expect(page.locator('[data-testid^="certificates-cancel-confirm-"]')).toContainText("되돌릴 수 없습니다");
  await page.locator('[data-testid^="certificates-cancel-go-"]').click();
  await expect(row).toHaveAttribute("data-status", "cancelled");
  await expect(page.getByTestId(`certificates-pick-${submissionId}`)).toBeEnabled();
});
