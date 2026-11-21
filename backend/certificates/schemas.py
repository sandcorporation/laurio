from __future__ import annotations

from datetime import date

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
