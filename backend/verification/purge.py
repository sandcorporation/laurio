"""신원 파기 절차 — 탈퇴와 휴면 파기가 공유하는 유일한 자리 (#470).

지금까지 탈퇴(`accounts.withdrawal.execute_withdrawal`)와 휴면 파기
(`accounts.dormancy._purge_dormant_identity`)가 같은 8개 `Verification` 필드를
각자 같은 순서로 비우고, 보존이 필요하면(`transaction_basis`) `RetainedIdentity`를
만드는 거의 같은 블록을 따로 갖고 있었다 — 필드가 하나 늘 때 한쪽을 빠뜨리면
조용한 개인정보 유출이다. 이 함수가 그 유일한 자리다: 호출부는 어떤 필드가
있는지 모른 채 `cause`(무엇 때문에 파기하는가)만 골라 부른다.

**옮기지 않은 것.** 거래 이력 판정(`accounts.withdrawal._transaction_basis`)과
탈퇴 자격 판정(`accounts.withdrawal.blocking_reasons`)은 그대로 `accounts`에
남는다 — "탈퇴할 수 있는가"는 공모전·지급·강의실 세 갈래를 보는 다른 질문이고,
그 사유 목록을 닫힌 집합으로 설계하는 일은 이 티켓 범위 밖이다(#470 Out of
Scope). 이 함수는 그 판정 결과(`transaction_basis`)만 입력으로 받는다 —
"왜 남기는가"를 스스로 판단하지 않는다.

`PhoneContact` 삭제는 여기 없다 — 휴면 파기는 파기 대상 계정이 항상
`Verification`을 갖지만(스캔 후보 자체가 그 존재를 전제한다), 탈퇴는 한 번도
본인확인하지 않은 계정도 받을 수 있어 `verification`이 `None`일 수 있다.
그 경우에도 전화번호는 지워야 하므로, 호출부가 `Verification` 유무와 무관하게
직접 지운다 — 한 줄짜리 부수 효과를 여기 넣으면 오히려 "verification이 없으면
전화번호도 안 지워진다"는 조건을 이 함수 안에 숨기게 된다.
"""

from __future__ import annotations

from typing import Literal

from .models import RETAINED_IDENTITY_RETENTION_PERIOD, RetainedIdentity, Verification

PurgeCause = Literal["withdrawal", "dormancy"]

# 파기 원인마다 다른 상태·문구. `verification.reason`은 이미 이 앱이 소유하는
# 값이다(`verification/api.py`의 미성년 거절 문구와 같은 자리) — 탈퇴·휴면의
# 문구도 여기 두면 호출부가 상태 enum을 몰라도 된다.
_STATUS_AND_REASON: dict[PurgeCause, tuple[str, str]] = {
    "withdrawal": (Verification.Status.WITHDRAWN, "탈퇴로 신원이 파기되었습니다."),
    "dormancy": (Verification.Status.EXPIRED, "2년간 행위가 없어 신원이 파기되었습니다."),
}


def purge_identity(
    verification: Verification,
    *,
    as_of,
    cause: PurgeCause,
    transaction_basis: tuple[str, int] | None,
) -> None:
    """`verification`의 신원 필드를 비우고, 거래 이력이 있으면 실명·생년월일을
    `RetainedIdentity`로 옮겨 남긴다.

    호출자가 트랜잭션 경계를 연다 — 탈퇴는 계정 비활성화·프로필 초기화와 같은
    트랜잭션 안에 있어야 하고, 휴면 파기는 행 하나만 다뤄 그럴 필요가 없어 두
    호출부의 경계가 다르기 때문이다. 이미 `RetainedIdentity`가 있으면(같은
    계정이 두 번 파기될 리 없지만, 방어적으로) 새로 만들지 않는다 — 그 행은
    `user`에 대해 OneToOne이라 두 번째 생성 시도는 `IntegrityError`로 죽는다.
    """

    status, reason = _STATUS_AND_REASON[cause]
    user = verification.user

    if transaction_basis is not None and not RetainedIdentity.objects.filter(user=user).exists():
        basis_reason, retained_because_id = transaction_basis
        retained = RetainedIdentity(
            user=user,
            reason=basis_reason,
            retained_because_id=retained_because_id,
            retained_until=as_of + RETAINED_IDENTITY_RETENTION_PERIOD,
        )
        retained.real_name = verification.real_name
        retained.birth_date = verification.birth_date
        retained.save()

    verification.status = status
    verification.reason = reason
    verification.real_name_encrypted = ""
    verification.birth_date_encrypted = ""
    verification.ci_encrypted = ""
    verification.ci_hash = ""
    verification.di_encrypted = ""
    verification.verified_at = None
    verification.save()
