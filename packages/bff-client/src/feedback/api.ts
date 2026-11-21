// 제보자 API 호출 (#1241, 스펙 #1237) — 두 앱이 같은 경로를 쓰므로 한 곳에 둔다.
// 경로는 BFF 프록시(`/api/backend/feedback/…`)이고 응답 타입은 생성된 스키마에서 온다.

import type { BffClient } from "../client";
import type { components } from "../schema.gen";
import { type ApiResult, FALLBACK_DETAIL } from "../result";

export type FeedbackReportIn = components["schemas"]["FeedbackReportIn"];
export type FeedbackReportOut = components["schemas"]["FeedbackReportOut"];
export type FeedbackReportListOut = components["schemas"]["FeedbackReportListOut"];
export type FeedbackStatusChangeOut = components["schemas"]["FeedbackStatusChangeOut"];
export type ScreenshotUploadUrlOut = components["schemas"]["ScreenshotUploadUrlOut"];
export type FeedbackApp = FeedbackReportIn["app"];
export type FeedbackKind = FeedbackReportIn["kind"];

export const FEEDBACK_BODY_MAX = 4000;
export const SCREENSHOT_MAX_BYTES = 5 * 1024 * 1024;
export const SCREENSHOT_TYPES = ["image/png", "image/jpeg", "image/webp"] as const;
export type ScreenshotType = (typeof SCREENSHOT_TYPES)[number];

const BASE = "/api/backend/feedback";

export function fetchPermission(client: BffClient): Promise<ApiResult<{ granted: boolean }>> {
  return client.get<{ granted: boolean }>(`${BASE}/permission`, { unauthorizedIsAnswer: true });
}

export function fetchReports(client: BffClient): Promise<ApiResult<FeedbackReportListOut[]>> {
  return client.get<FeedbackReportListOut[]>(`${BASE}/reports`);
}

export function fetchReport(client: BffClient, id: number): Promise<ApiResult<FeedbackReportOut>> {
  return client.get<FeedbackReportOut>(`${BASE}/reports/${id}`);
}

export function fetchScreenshotUrl(client: BffClient, id: number): Promise<ApiResult<{ download_url: string }>> {
  return client.get<{ download_url: string }>(`${BASE}/reports/${id}/screenshot`);
}

/** presigned POST 로 그림을 올리고 보고서에 넣을 키를 돌려준다. */
export async function uploadScreenshot(
  client: BffClient,
  blob: Blob,
): Promise<{ ok: true; key: string } | { ok: false; detail: string }> {
  const issued = await client.post<ScreenshotUploadUrlOut>(`${BASE}/screenshot-upload-url`, {
    content_type: blob.type,
  });
  if (!issued.ok) return { ok: false, detail: issued.detail };
  const form = new FormData();
  for (const [name, value] of Object.entries(issued.data.fields)) form.append(name, value);
  form.append("file", blob);
  try {
    // 버킷으로 곧장 간다 — 우리 쿠키를 실어 보내지 않는다.
    const response = await fetch(issued.data.upload_url, { method: "POST", body: form, credentials: "omit" });
    if (!response.ok) return { ok: false, detail: FALLBACK_DETAIL };
  } catch {
    return { ok: false, detail: FALLBACK_DETAIL };
  }
  return { ok: true, key: issued.data.object_key };
}

export function createReport(client: BffClient, payload: FeedbackReportIn): Promise<ApiResult<FeedbackReportOut>> {
  return client.post<FeedbackReportOut>(`${BASE}/reports`, payload);
}

export const KIND_LABELS: Record<string, string> = { suggestion: "제안", bug: "문제" };
export const STATUS_LABELS: Record<string, string> = {
  received: "접수",
  in_progress: "작업 중",
  deployed: "반영",
  declined: "반려",
};
export const APP_LABELS: Record<string, string> = { contest: "공모전", classroom: "강의실" };

export function formatReceivedAt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
