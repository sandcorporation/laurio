// 알림을 누르면 그것이 말하는 화면으로 보낸다(#329). 데이터는 이미 #303이
// context에 실어 뒀다 — 여기서는 그것으로 주소만 짓는다, 새로 만들지 않는다.
//
// **받는 사람에 따라 가는 곳이 다르다**(티켓 「가장 틀리기 쉬운 곳」): 채점
// 완료는 낸 사람(참여자)에게 가므로 참여자 화면으로, 예산 경고는 강사에게
// 가므로 클래스 설정으로 — 그 갈림은 백엔드가 수신자를 정하는 규칙
// (`backend/classroom/scoring.py`)과 같은 축이라, notification_type 하나가
// 목적지 하나를 정한다. 잘못 짝지으면 받는 사람에게 없는 화면(404)으로 보낸다.
//
// context에 필요한 키가 없으면(옛 알림, 예상 밖의 유형) `null`을 돌려준다 —
// 호출부는 그때 링크 없이 그린다. 가리키던 문제·클래스가 그 뒤 지워졌어도
// 여기서는 알 수 없다(`context`는 FK가 아니라 그때의 값을 그대로 둔 JSON
// 스냅샷이다) — 그 경우는 도착한 화면 자신의 "찾을 수 없습니다" 상태가 이미
// 처리한다.
import type { NotificationRow } from "./api";

export function notificationHref(notification: NotificationRow): string | null {
  const context = (notification.context ?? {}) as Record<string, unknown>;

  switch (notification.notification_type) {
    case "classroom_submission_scored": {
      const classId = context.class_id;
      const problemId = context.problem_id;
      if (typeof classId !== "number" || typeof problemId !== "number") return null;

      const submissionId = typeof context.submission_id === "number" ? context.submission_id : null;
      const base = `/classes/${classId}/problems/${problemId}/submit`;
      return submissionId === null ? base : `${base}#submission-${submissionId}`;
    }
    case "classroom_token_budget_warning": {
      const classId = context.class_id;
      if (typeof classId !== "number") return null;
      return `/classes/${classId}/settings#token-budget`;
    }
    default:
      return null;
  }
}
