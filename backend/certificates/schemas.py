from __future__ import annotations

from datetime import date, datetime

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
