// 알림 목록 화면(#304)이 쓰는 표시용 문구. 공개 앱(frontend/lib/notifications/
// format.ts)과 같은 이유로 백엔드 SMS 렌더러(`notifications/rendering.py`)와
// 분리돼 있다 — 강의실 알림은 애초에 SMS로 안 나가므로(#301) 그 렌더러가
// 이 유형들의 문구를 아예 갖고 있지도 않다. 이 파일이 유일한 문구 출처다.
import type { NotificationRow } from "./api";

export function describeNotification(notification: NotificationRow): string {
  const context = (notification.context ?? {}) as Record<string, unknown>;

  switch (notification.notification_type) {
    case "classroom_submission_scored": {
      const problemTitle =
        typeof context.problem_title === "string" ? context.problem_title : "문제";
      const attemptNumber =
        typeof context.attempt_number === "number" ? context.attempt_number : null;
      const passed = context.passed === true;
      const attemptLabel = attemptNumber !== null ? `${attemptNumber}번째 시도` : "제출";
      return `'${problemTitle}' ${attemptLabel} 채점이 끝났습니다 — ${passed ? "통과" : "미통과"}.`;
    }
    case "classroom_token_budget_warning": {
      const className = typeof context.class_name === "string" ? context.class_name : "클래스";
      return `'${className}' 클래스의 채점 예산이 경고 임계를 넘었습니다.`;
    }
    default:
      return "새 알림이 있습니다.";
  }
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ko-KR");
}
