import { expect, test } from "@playwright/test";

import { e2eRunId } from "../lib/run-id";
import { runSeed } from "../lib/seed-http";
import { establishDeveloperSession } from "../lib/session";

// 받는 사람의 상장 줄(#1130) — 내 참가 현황에서 받기·확인 페이지 닫기를 하면 확인 페이지가
// 「확인할 수 없는 상장」이 된다. 상장은 실제 발급 서비스로 심는다(PDF 를 그리고 저장소에 올린다).
type SeededCertificate = { developer_uid: string; certificate_id: number; number: string; token: string };

async function seedCertificate(): Promise<SeededCertificate> {
  return (await runSeed("certificate", { run_id: e2eRunId() })) as SeededCertificate;
}

// 발급은 서버가 PDF 를 그리는 일이라 1.8초까지 걸린다 — 시험 본문(3초 한도)에서 하면 화면 흐름이 한도를 넘는다(#1342).
// 두 시험이 볼 상장은 한도 밖 beforeAll 에서 심는다(시험마다 다른 받는 사람).
let closing: SeededCertificate;
let notified: SeededCertificate;
test.beforeAll(async () => {
  test.setTimeout(30_000);
  closing = await seedCertificate();
  notified = await seedCertificate();
});

test("받는 사람이 PDF 를 받고 확인 페이지를 닫으면 확인 페이지가 「확인할 수 없는 상장」이 된다", async ({ page }) => {
  const seeded = closing;
  await establishDeveloperSession(page, seeded.developer_uid);

  const row = page.getByTestId(`certificate-row-${seeded.certificate_id}`);
  await expect(row.getByTestId(`certificate-row-${seeded.certificate_id}-state`)).toHaveText("유효");
  await expect(row).toContainText(seeded.number);

  const pdfHref = await row.getByTestId(`certificate-row-${seeded.certificate_id}-pdf`).getAttribute("href");
  const pdf = await page.context().request.get(pdfHref ?? "");
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()["content-type"]).toBe("application/pdf");

  await row.getByTestId(`certificate-row-${seeded.certificate_id}-visibility`).click();
  await expect(row.getByTestId(`certificate-row-${seeded.certificate_id}-state`)).toHaveText(
    "유효 · 확인 페이지 닫힘",
  );
  await expect(row.getByTestId(`certificate-row-${seeded.certificate_id}-visibility`)).toHaveText("확인 페이지 열기");

  await page.goto(`/c/${seeded.token}`);
  await expect(page.getByTestId("certificate-verify-state")).toHaveText("확인할 수 없는 상장");
});

test("상장 알림에서 내 참가 현황으로 간다", async ({ page }) => {
  const seeded = notified;
  await establishDeveloperSession(page, seeded.developer_uid, "/console/notifications");

  const link = page.locator('[data-testid^="notification-link-"]');
  await expect(link).toHaveText("상장 보기");
  await expect(link).toHaveAttribute("href", "/console/participation");
});
