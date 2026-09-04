// 정책 화면이 쓰는 타입 (#76) — 응답 모양은 생성 타입 그대로다(#148). 남는 것은 화면의
// 어휘(운영자가 고칠 수 있는 필드와 그 문구)다: 이 목록은 응답 모양이 아니라 **이 화면이 편집을
// 허용하는 범위**이고, 백엔드의 `UPDATABLE_FIELDS` 와 짝을 이룬다.

import type { components } from "@laurio/bff-client/schema";

export type PlatformPolicy = components["schemas"]["PolicyOut"];
export type PolicyChangeEntry = components["schemas"]["PolicyChangeOut"];

export const POLICY_FIELDS = [
  "platform_fee_bps",
  "withholding_tax_bps",
  "withholding_necessary_expense_bps",
  "withholding_minor_income_exempt_won",
] as const;

export type PolicyField = (typeof POLICY_FIELDS)[number];

export type PlatformPolicyValues = Record<PolicyField, number>;

export const POLICY_FIELD_LABELS: Record<PolicyField, string> = {
  platform_fee_bps: "플랫폼 수수료율",
  withholding_tax_bps: "원천징수율",
  withholding_necessary_expense_bps: "필요경비율",
  withholding_minor_income_exempt_won: "과세최저한(원)",
};
