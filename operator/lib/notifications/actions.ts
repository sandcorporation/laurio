// 운영팀 알림 검색·보내기·이력 API 호출(#418) — 실패의 모양과 `detail` 정규화는
// `@codemit/bff-client`가 소유한다(#148, categories/actions.ts와 같은 계약).

import type { ApiResult } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { OperatorNotice, Recipient } from "./types";

export type { ApiFailure, ApiResult, ApiSuccess } from "@codemit/bff-client";

export function searchRecipients(q: string): Promise<ApiResult<Recipient[]>> {
  return bffClient.get<Recipient[]>(
    `/api/backend/operator/notifications/operator-notices/recipients?q=${encodeURIComponent(q)}`,
  );
}

export interface SendOperatorNoticeInput {
  recipientId: number;
  title: string;
  body: string;
}

export function sendOperatorNotice(
  input: SendOperatorNoticeInput,
): Promise<ApiResult<OperatorNotice>> {
  return bffClient.post<OperatorNotice>("/api/backend/operator/notifications/operator-notices", {
    recipient_id: input.recipientId,
    title: input.title,
    body: input.body,
  });
}

export function fetchOperatorNotices(): Promise<ApiResult<OperatorNotice[]>> {
  return bffClient.get<OperatorNotice[]>("/api/backend/operator/notifications/operator-notices");
}
