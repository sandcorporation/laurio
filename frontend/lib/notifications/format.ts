// 알림 목록 화면(#230)이 쓰는 표시용 문구. 백엔드의 SMS 본문 렌더러
// (`notifications/rendering.py`)와 **의도적으로 분리**돼 있다 — 매체가 다르다
// (문자 vs 웹 화면)와 대상 값이 다르다(웹은 벨·배지 톤이 있어도 되고, SMS는
// 90바이트 한도가 있다) 둘 다 한 번역표를 강제로 같이 쓰면 서로의 제약이
// 섞인다. `NotificationType` 값 자체(어떤 종류가 있는가)만 백엔드와 같은 이름을
// 공유한다 — 문구 내용까지 공유하지 않는다.
import type { NotificationOut } from "./types";

export function describeNotification(notification: NotificationOut): string {
  const context = (notification.context ?? {}) as Record<string, unknown>;
  const contestTitle = typeof context.contest_title === "string" ? context.contest_title : "";

  switch (notification.notification_type) {
    case "deadline_reminder":
      return context.role === "sponsor"
        ? `주최하신 '${contestTitle}' 공모전 마감이 곧 도래합니다.`
        : `참가하신 '${contestTitle}' 공모전 마감이 곧 도래합니다.`;
    case "judging_period_ending_reminder":
      return `주최하신 '${contestTitle}' 공모전의 심사기간 종료가 임박했습니다 — 선정 처리를 완료해주세요.`;
    case "distribution_final_warning": {
      const amount = typeof context.amount === "number" ? context.amount : 0;
      return `주최하신 '${contestTitle}' 공모전, 선정이 없으면 상금 ${amount.toLocaleString("ko-KR")}원이 참가자 전원에게 자동으로 균등 배분됩니다.`;
    }
    case "result_notice":
      if (context.outcome === "distributed") {
        const amount = typeof context.amount === "number" ? context.amount : 0;
        return `참가하신 '${contestTitle}' 공모전의 상금 배분 ${amount.toLocaleString("ko-KR")}원이 확정되었습니다.`;
      }
      return `참가하신 '${contestTitle}' 공모전에서 수상하셨습니다!`;
    case "scoring_complete":
      return `제출하신 '${contestTitle}' 공모전 채점이 완료됐습니다 — 이의제기 기간이 시작됩니다.`;
    case "appeal_ruled":
      return "제기하신 이의 심판이 완료됐습니다.";
    case "new_contest_in_category":
      return `관심 카테고리에 새 공모전 '${contestTitle}'이(가) 등록됐습니다.`;
    case "payout_awaits_you": {
      const message = typeof context.message === "string" ? context.message : "";
      return message || "지급 절차에 확인이 필요합니다 — codemit에서 확인해주세요.";
    }
    // 강의실 알림 둘(#301, #303)은 여기 나타나지 않는다 — 백엔드 `GET
    // /notifications/me`의 기본값(공개 앱이 쓰는 값)이 그 유형들을 아예
    // 빼고 준다(#345, `backend/notifications/api.py`의 `_scope_by_classroom`).
    // 강의실 화면(`classroom/lib/notifications/format.ts`)에만 문구가 있다.
    default:
      return "새 알림이 있습니다.";
  }
}

export const STATUS_LABELS: Record<string, string> = {
  queued: "발송 대기",
  deferred: "야간 연기 — 다음 날 오전 8시 이후 발송",
  sent: "발송됨",
  failed: "발송 실패(전 채널 소진)",
  blocked_no_opt_in: "옵트인 없음으로 차단",
  // `not_dispatched`(강의실 알림 전용 종결 상태, #301)는 여기 없다 — 그
  // 유형들이 이 목록에 도달하지 않으므로(위 `describeNotification` 주석,
  // #345) 이 화면에서는 이 상태값 자체를 만날 일이 없다.
};

export const CHANNEL_LABELS: Record<string, string> = {
  alimtalk: "알림톡",
  sms: "SMS",
  lms: "LMS",
};

export const DISPATCH_STATUS_LABELS: Record<string, string> = {
  pending: "발송 시도 중",
  sent: "성공",
  failed: "실패",
  indeterminate: "결과 불명(재시도 안 함)",
};

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ko-KR");
}
