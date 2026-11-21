import { expect, test } from "@playwright/test";

import {
  E2E_OPERATOR_PASSWORD,
  seedE2eOperator,
  seedE2eOperatorCertificates,
  sponsorCertificateCancelled,
} from "../../lib/seed-operator";
import { establishOperatorSession } from "../../lib/session";

// 운영자 앱 상장 목록과 취소(#1131, 스펙 #1071). 취소는 되돌릴 수 없어 확인 한 번을 거치고,
// 새로고침해도 서버 상태 그대로 「취소됨」이어야 한다.

test("발급 목록에서 번호·받는 사람·상태를 보고, 한 장을 취소하면 새로고침해도 취소됨이다", async ({ page }) => {
  const [operator, seeded] = await Promise.all([seedE2eOperator(), seedE2eOperatorCertificates()]);
  const [first, second] = seeded.certificates;
  await establishOperatorSession(
    page,
    operator.username,
    E2E_OPERATOR_PASSWORD,
    `/contests/${seeded.contest_id}/certificates`,
  );

  const row = page.getByTestId(`certificate-row-${first.id}`);
  await expect(row).toContainText(first.number);
  await expect(row).toContainText(first.recipient_name);
  await expect(page.getByTestId(`certificate-status-${first.id}`)).toHaveText("유효");

  await page.getByTestId(`certificate-cancel-${first.id}`).click();
  await expect(page.getByTestId(`certificate-cancel-warning-${first.id}`)).toBeVisible();
  await page.getByTestId(`certificate-cancel-confirm-${first.id}`).click();

  await expect(page.getByTestId(`certificate-status-${first.id}`)).toHaveText("취소됨");
  await expect(page.getByTestId(`certificate-cancel-${first.id}`)).toHaveCount(0);

  await page.reload();
  await expect(page.getByTestId(`certificate-status-${first.id}`)).toHaveText("취소됨");
  await expect(page.getByTestId(`certificate-status-${second.id}`)).toHaveText("유효");

  const cancelled = await sponsorCertificateCancelled(seeded.contest_id, seeded.sponsor_access);
  expect(cancelled[first.number]).not.toBeNull();
  expect(cancelled[second.number]).toBeNull();
});
