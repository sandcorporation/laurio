// 알림 목록 화면(#230)이 쓰는 표시용 문구. 백엔드의 SMS 본문 렌더러
// (`notifications/rendering.py`)와 **의도적으로 분리**돼 있다 — 매체가 다르다
// (문자 vs 웹 화면)와 대상 값이 다르다(웹은 벨·배지 톤이 있어도 되고, SMS는
// 90바이트 한도가 있다) 둘 다 한 번역표를 강제로 같이 쓰면 서로의 제약이
// 섞인다. `NotificationType` 값 자체(어떤 종류가 있는가)만 백엔드와 같은 이름을
// 공유한다 — 문구 내용까지 공유하지 않는다.
import type { NotificationOut } from "./types";

/** `supportEmail` 은 무료 공모전 「크기 초과」 보류 문구의 문의처(#989 A2) — 화면이 `lib/legal/contact` 에서 준다. */
export function describeNotification(
  notification: NotificationOut,
  { supportEmail = null }: { supportEmail?: string | null } = {},
): string {
  const context = (notification.context ?? {}) as Record<string, unknown>;
  const contestTitle =
    typeof context.contest_title === "string" ? context.contest_title : "";

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
    case "scoring_held_size": {
      // 대장 확정 #1446 의 문구(#989 A2). 무료 공모전에는 이의가 없어 문의처를 안내한다.
      const endsAt =
        typeof context.judging_ends_at === "string"
          ? context.judging_ends_at
          : null;
      const ends = endsAt ? new Date(endsAt).toLocaleString("ko-KR") : "미정";
      const head = `제출하신 '${contestTitle}' 공모전의 제출 크기가 채점 한도를 넘어 채점이 보류되었습니다.`;
      if (context.is_free === true) {
        return `${head} 심사 종료(${ends}) 때 0점으로 처리됩니다. 채점 결과에 문제가 있다고 생각하면 ${supportEmail ? `문의처(${supportEmail})` : "문의처"}로 알려 주세요.`;
      }
      return `${head} 심사 종료(${ends}) 때 필수 요건 전체 미달(0점)로 처리됩니다. 그 전까지 이의를 신청할 수 있습니다.`;
    }
    case "contest_updated":
      return `참가하신 '${contestTitle}' 공모전의 내용이 바뀌었습니다 — 바뀐 조건을 확인해주세요.`;
    case "certificate_issued":
      return `참가하신 '${contestTitle}' 공모전의 상장이 발급되었습니다.`;
    case "certificate_reissued":
      return `참가하신 '${contestTitle}' 공모전의 상장이 다시 발급되었습니다.`;
    case "score_corrected":
      return `제출하신 '${contestTitle}' 공모전의 점수를 플랫폼 오류로 다시 채점했습니다.`;
    case "certificate_score_corrected":
      return `주최하신 '${contestTitle}' 공모전에서 상장을 발급한 제출의 점수가 정정됐습니다 — 상장을 확인해주세요.`;
    case "feedback_status_changed": {
      const label = typeof context.status_label === "string" ? context.status_label : "";
      return label ? `보내신 제보가 '${label}' 상태로 바뀌었습니다.` : "보내신 제보의 상태가 바뀌었습니다.";
    }
    case "appeal_ruled":
      return "제기하신 이의 심판이 완료됐습니다.";
    case "new_contest_in_category":
      return `관심 카테고리에 새 공모전 '${contestTitle}'이(가) 등록됐습니다.`;
    case "payout_awaits_you": {
      const message =
        typeof context.message === "string" ? context.message : "";
      return (
        message || "지급 절차에 확인이 필요합니다 — codemit에서 확인해주세요."
      );
    }
    case "operator_notice":
      return notification.title
        ? `운영팀 알림: ${notification.title}`
        : "운영팀 알림이 도착했습니다.";
    // 강의실 알림 둘(#301, #303)은 여기 나타나지 않는다 — 백엔드 `GET
    // /notifications/me`의 기본값(공개 앱이 쓰는 값)이 그 유형들을 아예
    // 빼고 준다(#345, `backend/notifications/api.py`의 `_scope_by_classroom`).
    // 강의실 화면(`classroom/lib/notifications/format.ts`)에만 문구가 있다.
    default:
      return "새 알림이 있습니다.";
  }
}

/** 알림에서 이어지는 화면 — 상장 알림(#1130)은 받는 사람의 상장 줄이 있는 내 참가 현황으로 간다. */
export function notificationHref(notification: Pick<NotificationOut, "notification_type"> & { context?: unknown }): string | null {
  switch (notification.notification_type) {
    case "certificate_issued":
    case "certificate_reissued":
      return "/console/participation";
    case "feedback_status_changed": {
      const reportId = (notification.context as { report_id?: unknown } | null | undefined)?.report_id;
      return typeof reportId === "number" ? `/console/feedback/${reportId}` : "/console/feedback";
    }
    default:
      return null;
  }
}

export const STATUS_LABELS: Record<string, string> = {
  queued: "발송 대기",
  deferred: "야간 연기 — 다음 날 오전 8시 이후 발송",
  sent: "발송됨",
  failed: "발송 실패(전 채널 소진)",
  blocked_no_opt_in: "옵트인 없음으로 차단",
  // 강의실 알림(#301)과 운영팀 알림(#418) 둘 다 internal-only라 이 상태로
  // 끝난다 — 강의실 유형은 이 목록에 도달하지 않지만(#345), 운영팀 알림은
  // 도달하므로(공모전 쪽 알림이라 CLASSROOM_NOTIFICATION_TYPES에 없다) 여기
  // 라벨이 있어야 화면에 원문 상태값이 그대로 노출되지 않는다.
  not_dispatched: "앱 안에서만 전달됨",
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
