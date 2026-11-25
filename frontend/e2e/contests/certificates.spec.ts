// 개최자 「상장」 화면 (#1129, 스펙 #1071) — 마감 뒤 제출자를 골라 칸을 채우고 발급하면,
// 새로고침 뒤에도 목록에 남고, 취소하거나 고쳐 다시 발급할 수 있다. 칸의 규칙(길이·날짜·
// 금칙어·발급 수 한도)과 PDF 내용은 backend/tests/integration/test_certificate_issue.py 가 본다 —
// 여기서는 화면이 실제 스택에 닿는지만 본다.
import { expect, test, type Page } from "@playwright/test";

import { seedE2eContests } from "../lib/seed";
import { establishDeveloperSession } from "../lib/session";

// 준비는 화면이 아니라 API 로 — 상장 한 장을 미리 발급해 둔다(렌더가 있어 한 번에 1초 안팎).
async function issueViaApi(page: Page, id: number, submissionId: number, recipient = "홍길동"): Promise<void> {
  const { status, ms } = await page.evaluate(
    async ({ url, submissionId, recipient }) => {
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
                recipient_name: recipient,
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
    { url: `/api/backend/contests/${id}/certificates`, submissionId, recipient },
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
  // 둘째·셋째 시험이 볼 상장 두 장은 여기서 미리 발급해 둔다 — 발급은 PDF 렌더라 가끔 2초를 넘고, 그 시간이
  // 시험 한도(3초)를 먹으면 안 된다(#1176).
  const page = await browser.newPage();
  try {
    await establishDeveloperSession(page, seeded.judging.sponsor_login_seed, null);
    await page.goto("/"); // 같은 출처 fetch 를 하려면 about:blank 를 벗어나야 한다
    await issueViaApi(page, seeded.judging.id, seeded.judging.submissions[1].id);
    await issueViaApi(page, seeded.judging.id, seeded.judging.submissions[0].id, "김첫째");
  } finally {
    await page.close();
  }
});

async function openBoardWithoutLoading(page: Page, submissionIndex: number) {
  await establishDeveloperSession(page, seeded.judging.sponsor_login_seed, null);
  const { id, submissions } = seeded.judging;
  expect(submissions.length).toBeGreaterThan(submissionIndex);
  return { id, submissionId: submissions[submissionIndex].id };
}

async function openBoard(page: Page, submissionIndex: number) {
  await establishDeveloperSession(page, seeded.judging.sponsor_login_seed, null);
  const { id, submissions } = seeded.judging;
  expect(submissions.length).toBeGreaterThan(submissionIndex);
  await page.goto(`/console/contests/${id}/certificates`);
  await expect(page.getByTestId("certificates-contest-title")).toBeVisible();
  return { id, submissionId: submissions[submissionIndex].id };
}

// 한 시험 3초 한도(#1176) — 발급은 서버가 PDF 를 그리는 일이라 평소 0.4초, 부하가 걸리면 1.5~2.6초가
// 된다(백엔드 컨테이너에서 렌더만 60번 재면 중앙값 0.4초, 가끔 1.5초). 그 흔들림이 시험 한도를 먹지
// 않게 이 시험은 화면이 보내는 요청을 가로채 본다 — 보내는 칸(제출자·문구)을 단언하고, 응답은 서버가
// 주는 모양의 한 장으로 대신한다. 실제 발급(렌더·저장)은 beforeAll 의 API 발급, 아래 두 시험, 백엔드
// 시험이 본다.
test("제출자를 골라 상장을 발급하면 목록에 행이 생기고 그 사람은 더 고를 수 없다", async ({ page }) => {
  const { id, submissionId } = await openBoardWithoutLoading(page, 0);
  let sent: { items: { submission_id: number; text: Record<string, string> }[] } | null = null;
  let issued: Record<string, unknown> | null = null;
  await page.route(`**/api/backend/contests/${id}/certificates`, async (route) => {
    const request = route.request();
    if (request.method() === "POST") {
      sent = request.postDataJSON();
      const text = sent!.items[0].text;
      issued = {
        id: 9100, number: "E2E-9100", submission_id: sent!.items[0].submission_id,
        award_name: text.award_name, recipient_name: text.recipient_name, body: text.body,
        giver_name: text.giver_name, giver_title: text.giver_title, award_date: text.award_date,
        issued_at: "2026-11-20T00:00:00Z", cancelled_at: null, replaced_by_id: null,
        verify_url: "https://example.test/c/e2e", pdf_available: true,
      };
      await route.fulfill({ status: 201, json: [issued] });
      return;
    }
    const response = await route.fetch();
    const board = await response.json();
    // 이 제출자의 실제 상장(beforeAll 이 발급해 둔 것)은 가리고 아직 발급 전인 보드로 시작한다.
    board.certificates = board.certificates.filter((c: { submission_id: number }) => c.submission_id !== submissionId);
    board.recipients = board.recipients.map((r: { submission_id: number }) =>
      r.submission_id === submissionId ? { ...r, certificate_id: issued ? 9100 : null } : r,
    );
    if (issued) board.certificates = [issued, ...board.certificates];
    await route.fulfill({ response, json: board });
  });
  await page.goto(`/console/contests/${id}/certificates`);
  await expect(page.getByTestId("certificates-contest-title")).toBeVisible();

  await page.getByTestId(`certificates-pick-${submissionId}`).check();
  await page.getByTestId(`certificates-draft-${submissionId}-award-name`).fill("최우수상");
  await page.getByTestId("certificates-issue").click();
  // 되돌릴 수 없다는 경고가 먼저 뜬다 — 확인 전에는 보내지 않는다.
  await expect(page.getByTestId("certificates-confirm")).toContainText("고칠 수 없고");
  // 낭독기는 확인창에 들어가며 무엇을 하는지(장수·되돌릴 수 없음)를 듣는다(#1477).
  await expect(page.getByRole("alertdialog", { name: "상장 발급 확인" })).toHaveAccessibleDescription(/1장을 발급합니다.*고칠 수 없고/);
  expect(sent).toBeNull();
  await page.getByTestId("certificates-confirm-issue").click();

  const row = page.locator('[data-testid^="certificates-row-"]', { hasText: "최우수상" });
  await expect(row).toHaveCount(1);
  await expect(row).toHaveAttribute("data-status", "valid");
  expect(sent!.items).toHaveLength(1);
  expect(sent!.items[0].submission_id).toBe(submissionId);
  expect(sent!.items[0].text.award_name).toBe("최우수상");
  // 발급된 제출자는 더 고를 수 없다.
  await expect(page.getByTestId(`certificates-pick-${submissionId}`)).toBeDisabled();
});

test("발급한 상장 중 하나를 골라 받으면 버튼 글자와 받은 묶음이 고른 수와 맞는다", async ({ page }) => {
  const { id } = await openBoard(page, 1);
  const rows = page.locator('[data-testid^="certificates-row-"]');
  await expect(rows).toHaveCount(2);
  const bundle = page.getByTestId("certificates-bundle");
  await expect(bundle).toHaveText("묶음 받기 (전체 2)");

  const firstId = Number(((await rows.first().getAttribute("data-testid")) ?? "").replace("certificates-row-", ""));
  await page.getByTestId(`certificates-select-${firstId}`).check();
  await expect(bundle).toHaveText("고른 1장 받기");
  const [response, download] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/bundle.pdf")),
    page.waitForEvent("download"),
    bundle.click(),
  ]);
  expect(response.url()).toContain(`ids=${firstId}`);
  expect(response.status()).toBe(200);
  // 고른 한 장만 든 묶음 — 쪽수가 1.
  const file = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of file) chunks.push(chunk as Buffer);
  expect(Buffer.concat(chunks).toString("latin1")).toMatch(/\/Count 1\b/);

  // 고른 것을 풀면 전체로 돌아간다.
  await page.getByTestId(`certificates-select-${firstId}`).uncheck();
  await expect(bundle).toHaveText("묶음 받기 (전체 2)");
});

test("발급한 상장은 새로고침 뒤에도 남고, 취소하면 경고를 거쳐 「취소됨」이 되어 그 사람은 다시 고를 수 있다", async ({ page }) => {
  const { submissionId } = await openBoard(page, 1);

  const row = page.locator('[data-testid^="certificates-row-"]', { hasText: "홍길동" });
  await expect(row).toHaveCount(1);
  await expect(row).toHaveAttribute("data-status", "valid");
  await expect(page.getByTestId(`certificates-pick-${submissionId}`)).toBeDisabled();
  await row.getByRole("button", { name: "취소", exact: true }).click();
  await expect(page.locator('[data-testid^="certificates-cancel-confirm-"]')).toContainText("되돌릴 수 없습니다");
  await expect(page.getByRole("alertdialog", { name: /^\S+ 취소 확인$/ })).toHaveAccessibleDescription(
    /을\(를\) 취소합니다.*되돌릴 수 없습니다/,
  );
  await page.locator('[data-testid^="certificates-cancel-go-"]').click();
  await expect(row).toHaveAttribute("data-status", "cancelled");
  // 취소된 장에서 「취소」 단추가 사라진다 — 초점은 body 가 아니라 「발급한 상장」 머리글로 간다.
  await expect(page.getByRole("heading", { name: "발급한 상장" })).toBeFocused();
  // 취소된 상장은 묶음에 고를 수 없다.
  await expect(row.getByRole("checkbox")).toBeDisabled();
  await expect(page.getByTestId(`certificates-pick-${submissionId}`)).toBeEnabled();
});

// 확인창의 초점 규약(#1471 ⑥) — 열면 안전한 쪽(돌아가기), Tab 은 창 안에 갇히고, Escape·돌아가기는 닫고
// 연 자리로 돌아온다. 읽기만 한다(발급·취소를 보내지 않는다).
test("발급 확인창은 돌아가기에 초점을 두고 Tab 을 가두며 Escape 로 닫으면 발급 단추로 돌아온다", async ({ page }) => {
  const { id, submissionId } = await openBoardWithoutLoading(page, 0);
  await page.route(`**/api/backend/contests/${id}/certificates`, async (route) => {
    const response = await route.fetch();
    const board = await response.json();
    board.certificates = board.certificates.filter((c: { submission_id: number }) => c.submission_id !== submissionId);
    board.recipients = board.recipients.map((r: { submission_id: number }) =>
      r.submission_id === submissionId ? { ...r, certificate_id: null } : r,
    );
    await route.fulfill({ response, json: board });
  });
  await page.goto(`/console/contests/${id}/certificates`);
  await expect(page.getByTestId("certificates-contest-title")).toBeVisible();
  await page.getByTestId(`certificates-pick-${submissionId}`).check();
  await page.getByTestId("certificates-issue").focus();
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("alertdialog");
  const back = dialog.getByRole("button", { name: "돌아가기" });
  await expect(back).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(dialog.getByRole("button", { name: "발급", exact: true })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(back).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(dialog.getByRole("button", { name: "발급", exact: true })).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(page.getByTestId("certificates-issue")).toBeFocused();

  await page.keyboard.press("Enter");
  await page.getByRole("alertdialog").getByRole("button", { name: "돌아가기" }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(page.getByTestId("certificates-issue")).toBeFocused();
});

test("취소 확인창은 돌아가기에 초점을 두고 Tab 을 가두며 Escape 로 닫으면 취소 단추로 돌아온다", async ({ page }) => {
  await openBoard(page, 1);
  const row = page.locator('[data-testid^="certificates-row-"]', { hasText: "김첫째" });
  const opener = row.getByRole("button", { name: "취소", exact: true });
  await opener.focus();
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("alertdialog");
  const back = dialog.getByRole("button", { name: "돌아가기" });
  await expect(back).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(dialog.getByRole("button", { name: "취소하기" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(back).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
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
  // 파일 없는 장은 묶음에 고를 수 없다.
  await expect(page.getByTestId("certificates-select-9002")).toBeDisabled();
  await expect(page.getByTestId("certificates-select-9001")).toBeEnabled();
  // 묶음에는 파일 있는 한 장만 센다.
  await expect(page.getByTestId("certificates-bundle")).toHaveText("묶음 받기 (전체 1)");
});

// 「전체 선택」 — 고른 수와 결과를 낭독기가 듣는다(status). 읽기만 한다.
test("전체 선택은 고른 수를 status 로 알리고 다시 누르면 풀었다고 알린다", async ({ page }) => {
  const { id } = await openBoardWithoutLoading(page, 0);
  await page.route(`**/api/backend/contests/${id}/certificates`, async (route) => {
    const response = await route.fetch();
    const board = await response.json();
    board.certificates = [];
    board.recipients = board.recipients.map((r: object) => ({ ...r, certificate_id: null }));
    await route.fulfill({ response, json: board });
  });
  await page.goto(`/console/contests/${id}/certificates`);
  await expect(page.getByTestId("certificates-contest-title")).toBeVisible();
  const total = await page.locator('[data-testid^="certificates-recipient-"]').count();
  expect(total).toBeGreaterThan(0);
  await expect(page.getByTestId("certificates-picked-count")).toHaveAttribute("role", "status");
  await page.getByTestId("certificates-pick-all").check();
  await expect(page.getByTestId("certificates-pick-result")).toHaveText(`${total}명을 모두 선택했습니다.`);
  await expect(page.getByRole("status").filter({ hasText: `${total}/${total} 선택` })).toHaveCount(1);
  await page.getByTestId("certificates-pick-all").uncheck();
  await expect(page.getByTestId("certificates-pick-result")).toHaveText("선택을 모두 풀었습니다.");
  await expect(page.getByRole("status").filter({ hasText: `0/${total} 선택` })).toHaveCount(1);
});
