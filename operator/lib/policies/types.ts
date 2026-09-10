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
  // #263(ADR-0035) — 자리만 만든다. 값 자체는 아직 아무 동작도 바꾸지
  // 않는다(#261·#262·#264가 각자 읽어 쓴다).
  "max_source_asset_bytes",
  "max_demo_video_asset_bytes",
  "max_screenshot_asset_bytes",
  "max_build_asset_bytes",
  "demo_video_retention_grace_days",
  "max_screenshot_assets",
] as const;

export type PolicyField = (typeof POLICY_FIELDS)[number];

export type PlatformPolicyValues = Record<PolicyField, number>;

export const POLICY_FIELD_LABELS: Record<PolicyField, string> = {
  platform_fee_bps: "플랫폼 수수료율",
  withholding_tax_bps: "원천징수율",
  withholding_necessary_expense_bps: "필요경비율",
  withholding_minor_income_exempt_won: "과세최저한(원)",
  max_source_asset_bytes: "소스 업로드 용량 상한(바이트)",
  max_demo_video_asset_bytes: "시연 영상 업로드 용량 상한(바이트)",
  max_screenshot_asset_bytes: "스크린샷 업로드 용량 상한(바이트)",
  max_build_asset_bytes: "인수 산출물 업로드 용량 상한(바이트)",
  demo_video_retention_grace_days: "시연 영상 보존 유예일수",
  max_screenshot_assets: "스크린샷 개수 상한",
};
