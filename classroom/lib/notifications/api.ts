// 강의실 알림 백엔드 호출 (#304). 공유 엔드포인트(`/api/notifications/*`,
// backend `notifications/api.py`)를 공개 앱과 나눠 쓰되, `classroom_only=true`를
// 언제나 붙인다 — 목록도, 안 읽은 개수도, 읽음 처리도 강의실 알림
// (`CLASSROOM_NOTIFICATION_TYPES`)만 본다. 이 앱은 아직 `@laurio/bff-client`를
// 쓰지 않으므로(`lib/backend/client.ts`) 타입도 여기서 손으로 적는다 —
// `lib/submissions/api.ts`와 같은 패턴이다.
import { backendJson } from "@/lib/backend/client";

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

const PAGE_SIZE = 50;

export function fetchMyNotifications(limit: number = PAGE_SIZE, offset = 0): Promise<NotificationRow[]> {
  return backendJson<NotificationRow[]>(
    `/notifications/me?classroom_only=true&limit=${limit}&offset=${offset}`,
  );
}

export function fetchUnreadCount(): Promise<UnreadCount> {
  return backendJson<UnreadCount>("/notifications/unread-count?classroom_only=true");
}

export function markAllRead(): Promise<MarkAllRead> {
  return backendJson<MarkAllRead>("/notifications/mark-read?classroom_only=true", {
    method: "POST",
  });
}
