"""빠뜨린 필드를 구조 테스트가 막는다 — 모든 입력 문자열 필드를 규칙 표에
등록시킨다 (#480, spec #474).

**앞으로 사용자 입력을 받는 새 필드를 더하면, 금칙어 검사를 어떻게 할지
정하기 전까지 이 테스트가 빨갛다.** 백엔드 입력 스키마(django-ninja
`Schema`, 이름이 "In"으로 끝나는 관례)를 전부 찾아 문자열 필드를 모으고,
`core.banned_word_rules.RULES`에 전부 등록돼 있는지 본다. 등록되지 않은
필드가 있으면 실패한다. **면제(`checks_impersonation=False`이고
`checks_profanity=False`)인데 `exempt_reason`이 비어 있어도 실패한다** —
이유 없는 면제는 잊힌 누락과 구별되지 않는다. `tests/test_app_boundaries.py`
가 앱 경계 예외에 쓰는 것과 같은 관용구다.

**왜 "In"으로 끝나는 이름인가.** 이 저장소의 관례가 그렇다 —
`grep -rohn "payload: [A-Za-z_]*" backend`로 확인하면 라우터 핸들러의
`payload:` 타입 주석은 예외 없이 이 접미사를 쓰고, 중첩 스키마
(`SubmissionIn.assets: list[SubmissionAssetIn]`처럼 다른 `...In` 스키마를
품는 필드)도 같은 관례를 따른다. `RULES`에 이미 등록된 키도 전부 이
접미사를 쓴다. 조회·검색 조건 스키마("...Filters" 등)는 저장되지도 남에게
보이지도 않는 요청 파라미터라 범위 밖이다 — spec #474가 다루는 것은
저장되어 남이 읽는 이름·제목·본문이다.

**왜 AST가 아니라 클래스 임포트인가.** `test_app_boundaries.py`류는 AST로
import 문 자체(순환 참조 위험)를 본다 — 여기서 보는 것은 "이 필드가
문자열인가"라는 타입 판정이고, `Optional[str]`·`str | None`·
`Annotated[str, Field(...)]`이 전부 같은 뜻이라는 것은 pydantic이 이미
정확히 풀어 준다. `core.management.commands.export_openapi_schema`가 이미
같은 전제(스키마를 파이썬에서 그대로 읽어들이는 것은 "정적"이다 — DB도
HTTP도 필요 없다)로 스키마를 읽는다. 다만 그 명령의 OpenAPI 출력
(`components.schemas`)은 이름이 겹치는 두 클래스(`payments.WebhookIn`·
`payouts.WebhookIn`)를 하나로 뭉개 버린다(실측 — 한쪽 필드가 통째로
사라진다) — 그래서 여기서는 그 출력을 쓰지 않고 `ninja.Schema.
__subclasses__()`를 재귀로 걸어 실제 클래스 객체를 얻는다. 클래스 객체는
`(module, 클래스 이름)`으로 갈리므로 이름이 겹쳐도 뭉개지지 않는다.
"""

from __future__ import annotations

import types
import typing

import ninja

# 라우터·스키마 전부를 임포트해 `ninja.Schema.__subclasses__()`가 빈 목록을
# 돌려주지 않게 한다 — 이 모듈을 부르지 않으면 아직 임포트되지 않은 앱의
# 스키마가 조용히 스캔에서 빠진다.
from config.api import api  # noqa: F401
from core.banned_word_rules import RULES

_UNION_TYPES = (typing.Union, types.UnionType)


def _unwrap_optional(annotation: object) -> object:
    """`X | None`·`Optional[X]`을 `X`로 벗긴다. 그 밖의 Union(여러 실제
    타입을 묶은 것)은 이 저장소의 입력 스키마에 쓰인 적이 없으므로 손대지
    않고 그대로 돌려준다 — str도 아니고 list[str]도 아니라 스캔에서
    저절로 빠진다."""

    origin = typing.get_origin(annotation)
    if origin in _UNION_TYPES:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _all_subclasses(cls: type) -> list[type]:
    seen: set[type] = set()
    stack = [cls]
    out: list[type] = []
    while stack:
        current = stack.pop()
        for sub in current.__subclasses__():
            if sub not in seen:
                seen.add(sub)
                out.append(sub)
                stack.append(sub)
    return out


def _scan_user_input_string_fields() -> set[tuple[str, str, str]]:
    """`(앱 라벨, 입력 스키마 클래스 이름, 필드 이름)` 전부를 모은다 — 문자열
    필드, 그리고 문자열의 리스트인 필드(`list[str]`)까지. 앱 라벨은
    `RULES`의 관례와 같게 클래스가 정의된 모듈의 최상위 패키지
    (`cls.__module__.split(".")[0]`)를 쓴다 — Django 앱이 저장소 최상위
    패키지 그대로라 이 값이 곧 app label이다."""

    fields: set[tuple[str, str, str]] = set()
    seen_classes: set[tuple[str, str]] = set()
    for cls in _all_subclasses(ninja.Schema):
        if not cls.__name__.endswith("In"):
            continue
        app_label = cls.__module__.split(".")[0]
        class_key = (app_label, cls.__name__)
        if class_key in seen_classes:
            # 같은 (앱, 클래스 이름)이 두 번 나올 일은 없다 — 나온다면 그
            # 자체가 이름 충돌이라 조사할 일이지 조용히 건너뛸 일이 아니다.
            raise AssertionError(f"중복된 입력 스키마 등록: {class_key}")
        seen_classes.add(class_key)

        for field_name, field_info in cls.model_fields.items():
            annotation = _unwrap_optional(field_info.annotation)
            if annotation is str:
                fields.add((app_label, cls.__name__, field_name))
                continue
            origin = typing.get_origin(annotation)
            if origin in (list, typing.List):  # noqa: UP006 — get_origin이 list를 돌려준다
                args = typing.get_args(annotation)
                inner = _unwrap_optional(args[0]) if args else None
                if inner is str:
                    fields.add((app_label, cls.__name__, field_name))
    return fields


def test_every_scanned_field_is_registered():
    """등록되지 않은 사용자 입력 문자열 필드가 있으면 실패한다(#480 AC)."""

    scanned = _scan_user_input_string_fields()
    registered = set(RULES.keys())
    missing = sorted(scanned - registered)
    assert not missing, (
        "다음 입력 문자열 필드가 core.banned_word_rules.RULES에 없습니다 — "
        "금칙어 검사를 걸거나(BannedWordRule(checks_impersonation=..., "
        "checks_profanity=...)), 검사 대상이 아니면 exempt_reason을 채운 "
        "면제 항목을 더하세요.\n" + "\n".join(f"  {app}.{cls}.{field}" for app, cls, field in missing)
    )


def test_no_stale_registrations():
    """`RULES`에 있는데 지금은 스캔되지 않는 키가 있으면 실패한다 — 필드가
    지워지거나 이름이 바뀌었는데 표만 남은 상태다. `test_app_boundaries.py`
    의 "표가 INSTALLED_APPS와 어긋나면 실패한다"와 같은 방향의 신선도
    검사다."""

    scanned = _scan_user_input_string_fields()
    registered = set(RULES.keys())
    stale = sorted(registered - scanned)
    assert not stale, (
        "다음 항목은 core.banned_word_rules.RULES에 있지만 지금은 어떤 입력 "
        "스키마에도 없습니다 — 필드가 지워졌거나 이름이 바뀌었는데 표만 "
        "남았습니다. 지우세요.\n" + "\n".join(f"  {app}.{cls}.{field}" for app, cls, field in stale)
    )


def test_every_exemption_has_a_reason():
    """면제(사칭·욕설 둘 다 검사하지 않는 항목)인데 이유가 비어 있으면
    실패한다(#480 AC) — 이유 없는 면제는 잊힌 누락과 구별되지 않는다."""

    unexplained = sorted(
        f"{app}.{cls}.{field}"
        for (app, cls, field), rule in RULES.items()
        if not rule.checks_impersonation and not rule.checks_profanity and not rule.exempt_reason.strip()
    )
    assert not unexplained, (
        "다음 면제 항목에 exempt_reason이 없습니다 — 왜 검사하지 않는지 "
        "적으세요.\n" + "\n".join(f"  {name}" for name in unexplained)
    )


def test_checked_fields_do_not_also_carry_an_exempt_reason():
    """검사 대상(사칭·욕설 중 하나라도 참)인데 `exempt_reason`이 채워져 있으면
    실패한다 — 검사와 면제 이유가 동시에 있으면 어느 쪽이 실제 동작인지
    코드를 읽어야만 알 수 있다."""

    contradictory = sorted(
        f"{app}.{cls}.{field}"
        for (app, cls, field), rule in RULES.items()
        if (rule.checks_impersonation or rule.checks_profanity) and rule.exempt_reason.strip()
    )
    assert not contradictory, (
        "다음 항목은 금칙어 검사를 걸면서 exempt_reason도 채워져 있습니다 — "
        "검사 대상이면 exempt_reason을 비우세요.\n"
        + "\n".join(f"  {name}" for name in contradictory)
    )
