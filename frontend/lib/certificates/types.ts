import type { components } from "@codemit/bff-client/schema";

export type CertificateBoardOut = components["schemas"]["CertificateBoardOut"];
export type CertificateOut = components["schemas"]["CertificateOut"];
export type CertificateRecipientOut = components["schemas"]["CertificateRecipientOut"];
export type CertificateTextIn = components["schemas"]["CertificateTextIn"];

/** 한 번에 발급할 수 있는 최대 인원 — 백엔드 `CertificateIssueIn` 의 한도(#1127). */
export const ISSUE_BATCH_LIMIT = 50;

/** 칸마다 길이 한도 — 백엔드 입력 제한(#1071)과 같다. */
export const FIELD_LIMITS = {
  award_name: 20,
  recipient_name: 20,
  body: 120,
  giver_name: 30,
  giver_title: 30,
} as const;

export type CertificateStatus = "valid" | "replaced" | "cancelled";

/** 발급 목록의 상태 — 취소 뒤 다시 발급됐으면 「다시 발급됨」, 아니면 「취소됨」. */
export function certificateStatus(certificate: CertificateOut): CertificateStatus {
  if (certificate.cancelled_at === null) return "valid";
  return certificate.replaced_by_id === null ? "cancelled" : "replaced";
}

const SEOUL_DATE = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul" });

/** 오늘(서울)을 `YYYY-MM-DD` 로. */
export function todayInSeoul(now: Date = new Date()): string {
  return SEOUL_DATE.format(now);
}

/** 수여 날짜 기본값 — 오늘을 허용 범위 안으로 끌어 놓는다. */
export function defaultAwardDate(min: string, max: string, today: string = todayInSeoul()): string {
  if (today < min) return min;
  if (today > max) return max;
  return today;
}
