from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from ninja import Field, Schema

#: 칸마다 길이(스펙 #1071 「입력 제한」) — 본문 120자는 A4 가로 한 장에서 넘치지 않는 길이다.
AWARD_NAME_MAX = 20
RECIPIENT_NAME_MAX = 20
BODY_MAX = 120
GIVER_NAME_MAX = 30
GIVER_TITLE_MAX = 30


class CertificateTextIn(Schema):
    award_name: str = Field(max_length=AWARD_NAME_MAX)
    recipient_name: str = Field(max_length=RECIPIENT_NAME_MAX)
    body: str = Field(default="", max_length=BODY_MAX)
    giver_name: str = Field(max_length=GIVER_NAME_MAX)
    giver_title: str = Field(default="", max_length=GIVER_TITLE_MAX)
    award_date: date


#: 한 번에 발급하는 사람 수 — 한 장을 그리는 데 CPU 0.4초가 들어 요청 하나가 너무 길어지지 않게 한다.
ISSUE_BATCH_MAX = 50


class CertificateIssueItemIn(Schema):
    """받는 사람 한 명과 그 사람의 칸."""

    submission_id: int
    text: CertificateTextIn


class CertificateIssueIn(Schema):
    items: list[CertificateIssueItemIn] = Field(min_length=1, max_length=ISSUE_BATCH_MAX)


class CertificateOut(Schema):
    id: int
    number: str
    submission_id: int
    award_name: str
    recipient_name: str
    body: str
    giver_name: str
    giver_title: str
    award_date: date
    issued_at: datetime
    cancelled_at: datetime | None
    replaced_by_id: int | None
    verify_url: str
    #: 받는 사람이 탈퇴하면(#1130) 이름과 PDF 를 파기한다 — 그 상장은 거짓이 되고 받기·다시 발급이 없다.
    pdf_available: bool = True


class CertificateRecipientOut(Schema):
    """발급할 수 있는 사람(그 공모전의 제출자) 한 명."""

    submission_id: int
    #: 받는 사람 이름 칸의 기본값 — 프로필 표시 이름.
    default_recipient_name: str
    #: 지금 유효한 상장(없으면 null).
    certificate_id: int | None


class CertificateDefaultsOut(Schema):
    giver_name: str
    giver_title: str
    award_date_min: date
    award_date_max: date


class CertificateBoardOut(Schema):
    defaults: CertificateDefaultsOut
    recipients: list[CertificateRecipientOut]
    #: 발급한 것 전부(취소된 것 포함), 최근 것부터.
    certificates: list[CertificateOut]


class CertificateVerifyOut(Schema):
    """공개 확인 페이지 `/c/{token}`(#1128) — 상태마다 보여도 되는 칸만 채운다.

    - `valid`: 번호·공모전·상·받는 사람·수여자·발급일
    - `cancelled`: 번호·공모전·취소일, `reissued` 는 다시 발급됐는지(새 상장은 가리키지 않는다)
    - `hidden`: 받는 사람이 닫았거나 탈퇴 — 번호만
    """

    state: Literal["valid", "cancelled", "hidden"]
    number: str
    contest_title: str | None = None
    award_name: str | None = None
    recipient_name: str | None = None
    giver_name: str | None = None
    giver_title: str | None = None
    issued_on: date | None = None
    cancelled_on: date | None = None
    reissued: bool = False


class MyCertificateOut(Schema):
    """받는 사람의 상장 줄(#1130) — 내 참가 현황의 제출 행에 붙는다."""

    id: int
    submission_id: int
    contest_id: int
    contest_title: str
    number: str
    award_name: str
    state: Literal["valid", "cancelled"]
    hidden: bool
    verify_url: str


class CertificateVisibilityIn(Schema):
    hidden: bool
