// 개최자 「상장」 화면 (#1129, 스펙 #1071) — 마감 뒤 제출자를 골라 칸을 채우고 발급하면,
// 새로고침 뒤에도 목록에 남고, 취소하거나 고쳐 다시 발급할 수 있다. 칸의 규칙(길이·날짜·
// 금칙어·발급 수 한도)과 PDF 내용은 backend/tests/integration/test_certificate_issue.py 가 본다 —
// 여기서는 화면이 실제 스택에 닿는지만 본다.
import { expect, test, type Page } from "@playwright/test";

import { seedE2eContests } from "../lib/seed";
import { establishDeveloperSession } from "../lib/session";

// 준비는 화면이 아니라 API 로 — 상장 한 장을 미리 발급해 둔다(렌더가 있어 한 번에 1초 안팎).
async function issueViaApi(page: Page, id: number, submissionId: number): Promise<void> {
  const { status, ms } = await page.evaluate(
    async ({ url, submissionId }) => {
      const board = await (await fetch(url)).json();
      const max: string = board.defaults.award_date_max;
      const today = new Date().toISOString().slice(0, 10);
      const startedAt = performance.now();
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
      return { status: response.status, ms: Math.round(performance.now() - startedAt) };
    },
    { url: `/api/backend/contests/${id}/certificates`, submissionId },
  );
  test.info().annotations.push({ type: "issue-post-ms", description: String(ms) });
  expect(status).toBe(201);
}

// 시드는 한 번만 — 시험마다 시드(관리 명령 한 번)를 돌리면 시험 하나가 3초 한도의 절반을 쓴다(#1176).
// 시험끼리 제출자를 나눠 쓰고(첫째 0번, 둘째 1번) 순서대로 돈다.
test.describe.configure({ mode: "serial" });
let seeded: Awaited<ReturnType<typeof seedE2eContests>>;
test.beforeAll(async ({ browser }) => {
  test.setTimeout(20_000); // 준비(시드·로그인·발급 렌더)는 시험 한도 밖이다 — 한도는 시험 본문에만 건다
  seeded = await seedE2eContests();
  // 둘째 시험이 볼 상장은 여기서 미리 발급해 둔다 — 발급은 PDF 렌더라 가끔 2초를 넘고, 그 시간이
  // 시험 한도(3초)를 먹으면 안 된다(#1176).
  const page = await browser.newPage();
  try {
    await establishDeveloperSession(page, seeded.judging.sponsor_login_seed, null);
    await page.goto("/"); // 같은 출처 fetch 를 하려면 about:blank 를 벗어나야 한다
    await issueViaApi(page, seeded.judging.id, seeded.judging.submissions[1].id);
  } finally {
    await page.close();
  }
});

async function openBoard(page: Page, submissionIndex: number) {
  await establishDeveloperSession(page, seeded.judging.sponsor_login_seed, null);
  const { id, submissions } = seeded.judging;
  expect(submissions.length).toBeGreaterThan(submissionIndex);
  await page.goto(`/console/contests/${id}/certificates`);
  await expect(page.getByTestId("certificates-contest-title")).toBeVisible();
  return { id, submissionId: submissions[submissionIndex].id };
}

// 한 시험 3초 한도(#1176) — 화면으로 발급하는 이 시험은 발급(PDF 렌더) 한 번을 담고, 새로고침 뒤
// 유지는 API 로 미리 발급해 둔 아래 취소 시험이 본다(화면 발급 + 새로고침을 한 시험에 몰면 3초를 넘었다).
test("제출자를 골라 상장을 발급하면 목록에 행이 생기고 그 사람은 더 고를 수 없다", async ({ page }) => {
  const { submissionId } = await openBoard(page, 0);

  await page.getByTestId(`certificates-pick-${submissionId}`).check();
  await page.getByTestId(`certificates-draft-${submissionId}-award-name`).fill("최우수상");
  await page.getByTestId("certificates-issue").click();
  // 되돌릴 수 없다는 경고가 먼저 뜬다 — 확인 전에는 발급되지 않는다.
  await expect(page.getByTestId("certificates-confirm")).toContainText("고칠 수 없고");
  // 둘째 시험용으로 미리 발급해 둔 한 장뿐이다.
  const rows = page.locator('[data-testid^="certificates-row-"]');
  await expect(rows).toHaveCount(1);
  await page.getByTestId("certificates-confirm-issue").click();

  const row = rows.filter({ hasText: "최우수상" });
  await expect(rows).toHaveCount(2);
  await expect(row).toHaveCount(1);
  await expect(row).toHaveAttribute("data-status", "valid");
  // 발급된 제출자는 더 고를 수 없다.
  await expect(page.getByTestId(`certificates-pick-${submissionId}`)).toBeDisabled();
});

test("발급한 상장은 새로고침 뒤에도 남고, 취소하면 경고를 거쳐 「취소됨」이 되어 그 사람은 다시 고를 수 있다", async ({ page }) => {
  const { submissionId } = await openBoard(page, 1);

  const row = page.locator('[data-testid^="certificates-row-"]', { hasText: "홍길동" });
  await expect(row).toHaveCount(1);
  await expect(row).toHaveAttribute("data-status", "valid");
  await expect(page.getByTestId(`certificates-pick-${submissionId}`)).toBeDisabled();
  await row.getByRole("button", { name: "취소", exact: true }).click();
  await expect(page.locator('[data-testid^="certificates-cancel-confirm-"]')).toContainText("되돌릴 수 없습니다");
  await page.locator('[data-testid^="certificates-cancel-go-"]').click();
  await expect(row).toHaveAttribute("data-status", "cancelled");
  await expect(page.getByTestId(`certificates-pick-${submissionId}`)).toBeEnabled();
});

test("받는 사람이 탈퇴한 상장은 파일 없음으로 보이고 받기·다시 발급이 꺼진다", async ({ page }) => {
  await establishDeveloperSession(page, seeded.judging.sponsor_login_seed, null);
  const { id } = seeded.judging;
  const stamp = "2026-11-20T00:00:00Z";
  const fake = (n: number, pdfAvailable: boolean) => ({
    id: 9000 + n,
    number: `E2E-${n}`,
    recipient_name: `수상자${n}`,
    award_name: "우수상",
    body: "",
    giver_name: "개최자",
    giver_title: "",
    award_date: "2026-11-20",
    issued_at: stamp,
    cancelled_at: null,
    replaced_by_id: null,
    pdf_available: pdfAvailable,
  });
  // 탈퇴는 회원 쪽 사건이라 화면 시험은 보드 응답에 두 장(유효·탈퇴)을 얹어 본다.
  await page.route(`**/api/backend/contests/${id}/certificates`, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    const board = await response.json();
    await route.fulfill({ response, json: { ...board, certificates: [fake(1, true), fake(2, false)] } });
  });
  await page.goto(`/console/contests/${id}/certificates`);

  const gone = page.getByTestId("certificates-row-9002");
  await expect(gone).toContainText("받는 사람 탈퇴 — 파일 없음");
  await expect(page.getByTestId("certificates-download-9002")).toBeDisabled();
  await expect(page.getByTestId("certificates-reissue-9002")).toBeDisabled();
  await expect(page.getByTestId("certificates-cancel-9002")).toBeEnabled();
  await expect(page.getByTestId("certificates-download-9001")).toBeEnabled();
  // 묶음에는 파일 있는 한 장만 센다.
  await expect(page.getByTestId("certificates-bundle")).toHaveText("묶음 받기 (1)");
});
