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

test("받는 사람이 PDF 를 받고 확인 페이지를 닫으면 확인 페이지가 「확인할 수 없는 상장」이 된다", async ({ page }) => {
  const seeded = await seedCertificate();
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
  const seeded = await seedCertificate();
  await establishDeveloperSession(page, seeded.developer_uid, "/console/notifications");

  const link = page.locator('[data-testid^="notification-link-"]');
  await expect(link).toHaveText("상장 보기");
  await expect(link).toHaveAttribute("href", "/console/participation");
});
