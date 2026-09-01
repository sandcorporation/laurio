// 정책 화면 타입(#77). 백엔드(policies/schemas.py)의 PolicyOut·PolicyChangeOut과
// 1:1로 대응한다.

export const POLICY_FIELDS = [
  "platform_fee_bps",
  "withholding_tax_bps",
  "withholding_necessary_expense_bps",
  "withholding_minor_income_exempt_won",
] as const;

export type PolicyField = (typeof POLICY_FIELDS)[number];

export interface PlatformPolicyValues {
  platform_fee_bps: number;
  withholding_tax_bps: number;
  withholding_necessary_expense_bps: number;
  withholding_minor_income_exempt_won: number;
}

// GET 응답 — 낙관적 동시성에 쓰는 version이 함께 온다. PATCH할 때 이 값을
// expected_version으로 그대로 되돌려 보내야 한다(#76).
export interface PlatformPolicy extends PlatformPolicyValues {
  version: number;
  updated_at: string;
}

// before/after는 그 변경이 실제로 건드린 필드만 담은 부분 집합이다 — 건드리지
// 않은 필드는 나타나지 않는다.
export interface PolicyChangeEntry {
  id: number;
  operator_username: string;
  reason: string;
  before: Partial<Record<PolicyField, number>>;
  after: Partial<Record<PolicyField, number>>;
  changed_at: string;
}

export const POLICY_FIELD_LABELS: Record<PolicyField, string> = {
  platform_fee_bps: "플랫폼 수수료율",
  withholding_tax_bps: "원천징수율",
  withholding_necessary_expense_bps: "필요경비율",
  withholding_minor_income_exempt_won: "과세최저한(원)",
};
