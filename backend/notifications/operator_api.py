"""운영팀 알림 — 운영자 API (#418/#419, CONTEXT.md 「운영자 알림」).

이 라우터는 기본이 거부다 — `accounts.operator_api.router`와 같은 이유로
`OperatorAuth`가 라우터 전체에 걸려 있다. 화면의 「검색 → 작성(이미지 포함) →
확인 → 보내기, 그리고 이력」을 지원한다: 계정 검색, 이미지 업로드 주소 발급,
보내기, 발송 이력 목록, 보낸 운영자 자신의 이미지 다시 보기.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404
from ninja import Field, Router, Schema
from ninja.errors import HttpError

from core.operator_auth import OperatorAuth

from . import operator_notice_images
from .models import OperatorNotice
from .operator_notices import send_operator_notice

operator_router = Router(tags=["operator", "notifications"], auth=OperatorAuth())

# 검색어가 너무 짧으면 계정 전체를 훑는 것과 다를 바 없다 — 실수로 빈 문자열이나
# 한 글자를 보내는 요청이 테이블 전체를 스캔하지 않게 최소 길이를 둔다.
_MIN_QUERY_LENGTH = 2
_MAX_SEARCH_RESULTS = 20
# 이력 목록 한 번이 돌려줄 수 있는 최대 건수 — `notifications.api.
# NOTIFICATION_HISTORY_MAX_LIMIT`과 같은 이유(무제한 응답을 만들지 않는다).
_HISTORY_MAX_LIMIT = 100


class RecipientOut(Schema):
    id: int
    email: str
    # 이메일이 비어 있거나(소셜 제공자가 이메일 동의를 안 준 경우) 검색 결과를
    # 사람이 알아볼 수 있게 하는 보조 표시명 — 닉네임이 있으면 그것, 없으면
    # 이메일, 그마저 없으면 계정 id로 떨어진다(#390의 nickname과 같은 자리).
    display_name: str


def _display_name(user) -> str:
    nickname = (
        user.social_accounts.exclude(nickname="").values_list("nickname", flat=True).first()
    )
    if nickname:
        return nickname
    if user.email:
        return user.email
    return f"계정 #{user.id}"


@operator_router.get("/notifications/operator-notices/recipients", response=list[RecipientOut])
def search_recipients(request, q: str = ""):
    """이메일이나 닉네임으로 받는 사람 계정을 찾는다.

    Operator(`is_staff=True`) 계정은 애초에 검색 대상이 아니다 — 참가자와
    서로소인 신원이다(ADR-0018).
    """

    q = q.strip()
    if len(q) < _MIN_QUERY_LENGTH:
        return []

    users = (
        get_user_model()
        .objects.filter(is_staff=False)
        .filter(Q(email__icontains=q) | Q(social_accounts__nickname__icontains=q))
        .distinct()
        .order_by("id")[:_MAX_SEARCH_RESULTS]
    )
    return [RecipientOut(id=u.id, email=u.email, display_name=_display_name(u)) for u in users]


class ImageUploadUrlOut(Schema):
    object_key: str
    upload_url: str
    method: str
    fields: dict[str, str] = Field(default_factory=dict)
    expires_at: str


class ImageUploadUrlIn(Schema):
    content_type: str


@operator_router.post(
    "/notifications/operator-notices/image-upload-url", response=ImageUploadUrlOut
)
def request_image_upload_url(request, payload: ImageUploadUrlIn):
    """받는 사람·제목을 정하기 전에도 부를 수 있다 — 작성 화면이 이미지부터
    올린다(#419). 형식이 맞지 않으면 422(`operator_notice_images.
    request_upload_url`)."""

    presigned = operator_notice_images.request_upload_url(request.auth.id, payload.content_type)
    return ImageUploadUrlOut(
        object_key=presigned.object_key,
        upload_url=presigned.url,
        method=presigned.method,
        fields=presigned.fields,
        expires_at=presigned.expires_at.isoformat(),
    )


class SendOperatorNoticeIn(Schema):
    recipient_id: int
    title: str = Field(min_length=1, max_length=200)
    body: str = ""
    # presigned POST로 실제 바이트가 이미 올라간 뒤의 object_key(선택, #419).
    image_object_key: str = ""


class OperatorNoticeOut(Schema):
    notification_id: int
    recipient_id: int
    title: str
    body: str
    sent_by: str
    created_at: str
    read_at: str | None
    has_image: bool = False


def _serialize_operator_notice(notice: OperatorNotice) -> OperatorNoticeOut:
    notification = notice.notification
    return OperatorNoticeOut(
        notification_id=notification.pk,
        recipient_id=notification.recipient_id,
        title=notice.title,
        body=notice.body,
        sent_by=notice.sent_by.username,
        created_at=notification.created_at.isoformat(),
        read_at=notification.read_at.isoformat() if notification.read_at else None,
        has_image=bool(notice.image_object_key),
    )


@operator_router.post("/notifications/operator-notices", response=OperatorNoticeOut)
def send_notice(request, payload: SendOperatorNoticeIn):
    """제목·본문을 받는 사람 한 명에게 보낸다. 받는 사람이 없으면 422다(AC) —
    존재하지 않는 계정으로 보내려는 요청 자체가 틀린 입력이라, 자원을 못
    찾았다는 404가 아니라 입력 검증 실패로 답한다. 빈 제목은 스키마의
    `Field(min_length=1)`이 같은 422로 걸러낸다.

    `image_object_key`가 이 요청을 보낸 운영자의 업로드 응답에서 나온 것이
    아니면 422다(#419) — 남의 업로드 키를 추측해 붙이는 경로를 막는다."""

    recipient = get_user_model().objects.filter(pk=payload.recipient_id, is_staff=False).first()
    if recipient is None:
        raise HttpError(422, "받는 사람을 찾을 수 없습니다.")

    image_object_key = payload.image_object_key
    if image_object_key:
        operator_notice_images.assert_owned_by(image_object_key, request.auth.id)

    notification = send_operator_notice(
        sender=request.auth,
        recipient=recipient,
        title=payload.title,
        body=payload.body,
        image_object_key=image_object_key,
    )
    return _serialize_operator_notice(notification.operator_notice)


@operator_router.get("/notifications/operator-notices", response=list[OperatorNoticeOut])
def list_operator_notices(request, limit: int = 50, offset: int = 0):
    """발송 이력 — 받는 사람·보낸 운영자·시각·읽음 여부. 최신순이고 수정·삭제
    엔드포인트는 없다(append-only)."""

    limit = max(1, min(limit, _HISTORY_MAX_LIMIT))
    offset = max(0, offset)
    notices = (
        OperatorNotice.objects.select_related("notification", "sent_by")
        .order_by("-notification__created_at")[offset : offset + limit]
    )
    return [_serialize_operator_notice(notice) for notice in notices]


class ImageDownloadOut(Schema):
    download_url: str
    expires_at: str


@operator_router.get(
    "/notifications/operator-notices/{int:notification_id}/image-download",
    response=ImageDownloadOut,
)
def download_operator_notice_image_as_sender(request, notification_id: int):
    """이력에서 보낸 이미지를 다시 연다(#419 User Story 8) — **보낸 운영자
    본인**만 열 수 있다, 다른 운영자는 404다(존재 자체를 알려주지 않는다)."""

    notice = get_object_or_404(
        OperatorNotice, notification_id=notification_id, sent_by=request.auth
    )
    if not notice.image_object_key:
        raise HttpError(404, "이미지가 없습니다.")

    presigned = operator_notice_images.request_download_url(notice.image_object_key)
    return ImageDownloadOut(
        download_url=presigned.url, expires_at=presigned.expires_at.isoformat()
    )
