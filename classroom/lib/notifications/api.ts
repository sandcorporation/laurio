// 강의실 알림 백엔드 호출 (#304). 공유 엔드포인트(`/api/notifications/*`,
// backend `notifications/api.py`)를 공개 앱과 나눠 쓰되, `classroom_only=true`를
// 언제나 붙인다 — 목록도, 안 읽은 개수도, 읽음 처리도 강의실 알림
// (`CLASSROOM_NOTIFICATION_TYPES`)만 본다. 공유 클라이언트 위에 선다(#462).
import type { ApiResult } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

export type NotificationDispatchRow = {
  id: number;
  channel: string;
  status: string;
  attempted_at: string;
  failure_reason: string;
};

// 지금 강의실이 만드는 유형 둘 — 배지·목록·묶기(#305)가 이 값으로 분기한다.
// 문자열 그대로 비교한다: 백엔드 `NotificationType`과 같은 값이어야 하고, 새
// 유형이 생기면 여기 추가한다(`fallback` 문구가 있어 빠뜨려도 화면이 죽지 않는다).
export type ClassroomNotificationType =
  | "classroom_submission_scored"
  | "classroom_token_budget_warning";

export type NotificationRow = {
  id: number;
  notification_type: string;
  is_transactional: boolean;
  is_promotional: boolean;
  status: string;
  scheduled_for: string | null;
  created_at: string;
  context: Record<string, unknown>;
  dispatches: NotificationDispatchRow[];
  read_at: string | null;
};

export type UnreadCount = { count: number };
export type MarkAllRead = { marked_count: number };

// 커서(keyset) 목록 응답(#151, #466) — `usePagedList`(패키지 hooks.ts)가
// 기대하는 `{items, count, next}` 계약 그대로다.
export type NotificationPage = {
  items: NotificationRow[];
  count: number;
  next: string | null;
};

// `after`가 없으면 처음부터, 있으면 그 다음부터다(#466) — 예전에는 최신
// 50건만 읽어(`limit`/`offset`) 51번째 이후의 안 읽은 알림이 이 화면에
// 존재하지 않았다(헤더 배지는 전체를 세므로 서로 어긋났다).
export function fetchMyNotifications(after?: string | null): Promise<ApiResult<NotificationPage>> {
  const cursor = after ? `&after=${encodeURIComponent(after)}` : "";
  return bffClient.get<NotificationPage>(`/api/backend/notifications/me?classroom_only=true${cursor}`);
}

export function fetchUnreadCount(): Promise<ApiResult<UnreadCount>> {
  return bffClient.get<UnreadCount>("/api/backend/notifications/unread-count?classroom_only=true");
}

export function markAllRead(): Promise<ApiResult<MarkAllRead>> {
  return bffClient.post<MarkAllRead>("/api/backend/notifications/mark-read?classroom_only=true");
}

// 알림 하나를 지목해 읽음으로 표시한다(#345) — 링크를 눌러 그 화면으로 갈 때,
// 또는 링크 없는 알림 줄의 「읽음」 버튼이 부른다. `classroom_only`가 필요
// 없다 — 이 엔드포인트는 이미 그 사람 소유의 알림 id 하나만 다루므로(백엔드
// `mark_one_read`가 `recipient=request.auth_user`로 조회한다), 어느 제품
// 것인지는 id 자체가 이미 정해 준다.
export function markOneRead(notificationId: number): Promise<ApiResult<NotificationRow>> {
  return bffClient.post<NotificationRow>(`/api/backend/notifications/${notificationId}/mark-read`);
}

// 알림 여러 개를 한 번에 지목해 읽음으로 표시한다(#345) — 묶음(#305)의 머리글을
// 누르면 그 문제의 안 읽은 시도 전부가 한 번에 읽음이 되어야 하는데, 그 개수만큼
// `markOneRead`를 따로 부르면 시도가 쌓일수록 요청 수가 그만큼 는다. 이쪽도
// `classroom_only`가 필요 없다 — id들 자체가 `recipient=request.auth_user`로
// 좁혀진다(백엔드 `mark_many_read`).
export function markManyRead(notificationIds: number[]): Promise<ApiResult<MarkAllRead>> {
  return bffClient.post<MarkAllRead>("/api/backend/notifications/mark-read-many", {
    notification_ids: notificationIds,
  });
}
