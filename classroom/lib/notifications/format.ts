// 알림 목록 화면(#304)이 쓰는 표시용 문구. 공개 앱(frontend/lib/notifications/
// format.ts)과 같은 이유로 백엔드 SMS 렌더러(`notifications/rendering.py`)와
// 분리돼 있다 — 강의실 알림은 애초에 SMS로 안 나가므로(#301) 그 렌더러가
// 이 유형들의 문구를 아예 갖고 있지도 않다. 이 파일이 유일한 문구 출처다.
import type { NotificationRow } from "./api";

export function describeNotification(notification: NotificationRow): string {
  const context = (notification.context ?? {}) as Record<string, unknown>;

  switch (notification.notification_type) {
    case "classroom_submission_scored": {
      const className = typeof context.class_name === "string" ? context.class_name : "클래스";
      const problemTitle =
        typeof context.problem_title === "string" ? context.problem_title : "문제";
      const attemptNumber =
        typeof context.attempt_number === "number" ? context.attempt_number : null;
      const passed = context.passed === true;
      const attemptLabel = attemptNumber !== null ? `${attemptNumber}번째 시도` : "제출";
      return `'${className}' 클래스 '${problemTitle}' 문제 ${attemptLabel} 채점 결과 — ${
        passed ? "통과" : "미통과"
      }.`;
    }
    case "classroom_scoring_key_rejected": {
      const className = typeof context.class_name === "string" ? context.class_name : "클래스";
      return `'${className}' 클래스의 채점 키가 거부되어 채점이 멈췄습니다 — 클래스 설정에서 새 키를 저장해 주세요.`;
    }
    case "classroom_scoring_quota_exhausted": {
      const className = typeof context.class_name === "string" ? context.class_name : "클래스";
      return `'${className}' 클래스 채점 키의 크레딧이 떨어져 채점이 멈췄습니다 — 충전하면 밀린 제출부터 이어서 채점됩니다. 참여자의 시도는 미달로 처리되지 않습니다.`;
    }
    case "classroom_scoring_server_unreachable": {
      const className = typeof context.class_name === "string" ? context.class_name : "클래스";
      return `'${className}' 클래스의 채점 서버에 닿지 않아 채점이 멈췄습니다 — 서버가 다시 열리면 밀린 제출부터 이어서 채점됩니다. 참여자의 시도는 미달로 처리되지 않습니다.`;
    }
    case "classroom_contest_entry_rejected": {
      const problemTitle =
        typeof context.problem_title === "string" ? context.problem_title : "문제";
      const attemptNumber =
        typeof context.attempt_number === "number" ? context.attempt_number : null;
      const reason = typeof context.reason === "string" && context.reason ? ` — ${context.reason}` : "";
      const attemptLabel = attemptNumber !== null ? `${attemptNumber}번째 시도` : "시도";
      return `'${problemTitle}' ${attemptLabel}는 공모전에는 내지 못했습니다${reason}. 클래스 제출과 채점은 그대로입니다.`;
    }
    // 소유권 이전(#575) — 요청은 받는 공동 강사가, 수락·거절은 요청한 사람이 받는다.
    case "classroom_ownership_transfer_requested": {
      const className = typeof context.class_name === "string" ? context.class_name : "클래스";
      const requester =
        typeof context.requester_display_name === "string" && context.requester_display_name
          ? `${context.requester_display_name}님이`
          : "소유자가";
      const until =
        typeof context.expires_at === "string" ? `${formatShortDateTime(context.expires_at)}까지` : "7일 안에";
      return `${requester} '${className}' 클래스의 소유권을 나에게 넘기려 합니다 — 넘겨받으면 지금 채점 키가 비워져 내 채점 키를 넣어야 채점이 이어집니다. ${until} 클래스 화면에서 수락하거나 거절해 주세요.`;
    }
    case "classroom_ownership_transfer_accepted": {
      const className = typeof context.class_name === "string" ? context.class_name : "클래스";
      const recipient = recipientSubject(context);
      return `${recipient} '${className}' 클래스의 소유권을 넘겨받았습니다 — 이제 나는 이 클래스의 공동 강사입니다.`;
    }
    case "classroom_ownership_transfer_declined": {
      const className = typeof context.class_name === "string" ? context.class_name : "클래스";
      const recipient = recipientSubject(context);
      return `${recipient} '${className}' 클래스의 소유권 이전 요청을 거절했습니다 — 소유권은 그대로 나에게 있습니다.`;
    }
    default:
      return "새 알림이 있습니다.";
  }
}

// 이름이 없으면 조사가 달라진다(님이 · 공동 강사가) — 소유권 이전 카드와 같은 규칙.
function recipientSubject(context: Record<string, unknown>): string {
  return typeof context.recipient_display_name === "string" && context.recipient_display_name
    ? `${context.recipient_display_name}님이`
    : "받는 공동 강사가";
}

function formatShortDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ko-KR", { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ko-KR");
}
