"""Notification 을 실제 채널에 보낼 문구로 렌더링한다 (#51).

여기서는 절대 자르지 않는다 — 길이가 SMS 한도를 넘는지, 그래서 SMS로 보낼지
LMS로 보낼지의 판단은 렌더링이 아니라 어댑터(`notifications.adapters_aligo`)의
몫이다(#51 AC: "길이가 SMS 한도를 넘으면 잘리지 않고 LMS로 나간다" — 이 함수가
자르면 그 판단 자체가 무의미해진다).
"""

from __future__ import annotations

from .models import Notification, NotificationType

_BRAND_PREFIX = "[Codemit]"


def render_message(notification: Notification) -> str:
    """`notification.notification_type`과 `notification.context`(#19)로부터
    사람이 읽을 문구를 만든다.

    아직 문구가 정의되지 않은 유형(향후 NotificationType 추가)은 크래시 대신
    최소한의 일반 문구로 폴백한다 — 발송 자체가 막히는 것보다 문구가 덜
    구체적인 편이 낫다(ADR-0009의 "미도달보다 낫다"는 기존 트레이드오프와
    같은 방향).
    """

    context = notification.context or {}
    contest_title = context.get("contest_title", "")
    notification_type = notification.notification_type

    if notification_type == NotificationType.DEADLINE_REMINDER:
        if context.get("role") == "sponsor":
            return f"{_BRAND_PREFIX} 주최하신 '{contest_title}' Contest 마감이 곧 도래합니다."
        return f"{_BRAND_PREFIX} 참가하신 '{contest_title}' Contest 마감이 곧 도래합니다."

    if notification_type == NotificationType.JUDGING_PERIOD_ENDING_REMINDER:
        return (
            f"{_BRAND_PREFIX} 주최하신 '{contest_title}' Contest의 심사기간 종료가 "
            "임박했습니다. codemit에서 Award 처리를 완료해 주세요."
        )

    if notification_type == NotificationType.DISTRIBUTION_FINAL_WARNING:
        amount = context.get("amount") or 0
        due_at = context.get("distribution_due_at", "")
        return (
            f"{_BRAND_PREFIX} 주최하신 '{contest_title}' Contest, Award가 없으면 "
            f"{due_at} 이후 상금 {amount:,}원 전액이 참가자 전원에게 자동으로 균등 "
            "배분되며 이후에는 환불되지 않습니다. 지금 codemit에서 Award를 확정해 "
            "주세요 — 상금을 잃지 않으시려면 지금 바로 확인하시기 바랍니다."
        )

    if notification_type == NotificationType.RESULT_NOTICE:
        if context.get("outcome") == "distributed":
            amount = context.get("amount") or 0
            return (
                f"{_BRAND_PREFIX} 참가하신 '{contest_title}' Contest의 상금 배분 "
                f"{amount:,}원이 확정되었습니다. codemit에서 확인하세요."
            )
        return f"{_BRAND_PREFIX} 참가하신 '{contest_title}' Contest에서 수상하셨습니다! codemit에서 확인하세요."

    if notification_type == NotificationType.SCORING_COMPLETE:
        return (
            f"{_BRAND_PREFIX} 제출하신 '{contest_title}' Contest 채점이 완료됐습니다. "
            "이의제기 기간이 시작됩니다 — codemit에서 확인하세요."
        )

    if notification_type == NotificationType.APPEAL_RULED:
        return f"{_BRAND_PREFIX} 제기하신 이의 심판이 완료됐습니다. codemit에서 결과를 확인하세요."

    if notification_type == NotificationType.NEW_CONTEST_IN_CATEGORY:
        return f"{_BRAND_PREFIX} 관심 카테고리에 새 Contest '{contest_title}'가 등록됐습니다."

    if notification_type == NotificationType.PAYOUT_AWAITS_YOU:
        # `payouts.notifications._notify_if_developer_turn`가 이미 context에
        # `message`(payouts.progress.next_action_message — Hold별 사람이 읽을
        # 문장, #169)를 실어 보낸다(#229). 여기서 새 번역표를 만들지 않는다 —
        # Hold → 문구 규칙은 `payouts.progress` 하나에만 있어야 한다(그 모듈
        # 독스트링, #130이 세 렌더러를 하나로 모은 이유). 그 값이 없으면(정의상
        # 없어서는 안 되지만, 방어적으로) 아래 공통 폴백으로 떨어진다 — 이름·
        # 연락처·계좌는 이 context에 애초에 없으므로(위 함수 참고) 새로
        # 담을 것도 없다.
        message = context.get("message")
        if message:
            return f"{_BRAND_PREFIX} {message}"

    if notification_type == NotificationType.CLASSROOM_TOKEN_BUDGET_WARNING:
        class_name = context.get("class_name", "")
        return (
            f"{_BRAND_PREFIX} '{class_name}' 클래스의 채점 예산이 경고 임계를 "
            "넘었습니다. codemit에서 사용량을 확인해 주세요."
        )

    return f"{_BRAND_PREFIX} 새 알림이 있습니다. codemit에서 확인하세요."
