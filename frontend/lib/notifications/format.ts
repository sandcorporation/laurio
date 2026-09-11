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
      return message || "지급 절차에 확인이 필요합니다 — laurio에서 확인해주세요.";
    }
    // 강의실 알림 둘(#301, #303)도 계정을 공유하는 한 사람에게는 이 목록에
    // 함께 쌓인다(#304 AC: "공개 앱의 알림 화면과 종은 바뀌지 않는다 — 거기서는
    // 여전히 전부 보인다") — 그래서 이 목록도 그 유형들을 알아야 일반 문구
    // ("새 알림이 있습니다")로 뭉개지 않는다. 문구 자체는 강의실 화면(`classroom/
    // lib/notifications/format.ts`)과 같은 내용이다 — 매체가 같은 웹 화면이라
    // 위 SMS/화면 분리 이유가 여기엔 적용되지 않는다.
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
    case "classroom_token_budget_warning": {
      const className = typeof context.class_name === "string" ? context.class_name : "클래스";
      const usageTotal =
        typeof context.token_usage_total === "number" ? context.token_usage_total : null;
      const budget = typeof context.token_budget === "number" ? context.token_budget : null;
      const percent =
        usageTotal !== null && budget ? Math.min(999, Math.round((usageTotal / budget) * 100)) : null;
      const usageLabel =
        percent !== null
          ? `사용량이 채점 예산의 ${percent}%를 넘었습니다`
          : "채점 예산이 얼마 남지 않았습니다";
      return `'${className}' 클래스, ${usageLabel} — 다 쓰면 새 채점이 멈추고 제출만 쌓입니다. 클래스 설정에서 채점 예산을 확인해 주세요.`;
    }
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
  // 강의실 알림 둘은 애초에 어느 채널로도 나가지 않는다(#301) — "발송 안 함"이
  // 그래서 실패가 아니라 이 알림의 정상적인 종결 상태다. 그 사실을 말하지
  // 않으면 원문 상태값("not_dispatched")이 그대로 노출되거나 다른 실패
  // 문구와 나란히 보여 실패처럼 읽힌다.
  not_dispatched: "발송 안 함 — 클래스 알림은 화면에서만 확인됩니다",
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
