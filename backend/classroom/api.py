"""Classroom API (#278, ADR-0037).

**강사 전용이다.** 참여자가 가입 링크로 들어와 보는 표면은 이 티켓의 범위
밖이다(#279 가입 링크 발급 · #280 가입 처리가 아직 없다) — `ClassMember`가
없는 지금은 "참여자"를 가려낼 방법이 없으므로, 강사가 아닌 모든 요청은 그
클래스가 아예 없는 것처럼 404를 받는다.
"""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth

from .models import Class
from .schemas import ClassIn, ClassOut, ErrorOut

router = Router(tags=["classroom"])


def _serialize_class(class_obj: Class) -> ClassOut:
    return ClassOut(id=class_obj.id, name=class_obj.name, created_at=class_obj.created_at)


def _get_owned_class_or_404(class_id: int, user_id: int) -> Class:
    """강사 본인의 클래스만 돌려준다. 남의 것은 「없다」로 답한다 — 목록에도
    상세에도 나오지 않아야 한다는 AC(#278)를 403이 아니라 404로 지킨다."""

    try:
        return Class.objects.get(id=class_id, instructor_id=user_id)
    except Class.DoesNotExist as exc:
        raise HttpError(404, "클래스를 찾을 수 없습니다.") from exc


@router.post("/classes", response={201: ClassOut}, auth=jwt_auth)
def create_class(request: HttpRequest, payload: ClassIn):
    class_obj = Class.objects.create(instructor_id=request.auth_user.id, name=payload.name)
    return 201, _serialize_class(class_obj)


@router.get("/classes", response={200: list[ClassOut]}, auth=jwt_auth)
def list_my_classes(request: HttpRequest):
    """「내 클래스」— 본인이 강사인 것만. 남의 클래스는 여기 나오지 않는다."""

    classes = Class.objects.filter(instructor_id=request.auth_user.id)
    return 200, [_serialize_class(c) for c in classes]


@router.get("/classes/{class_id}", response={200: ClassOut, 404: ErrorOut}, auth=jwt_auth)
def get_class(request: HttpRequest, class_id: int):
    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    return 200, _serialize_class(class_obj)
