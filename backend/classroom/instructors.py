"""「이 사람이 이 클래스의 강사인가」와 「소유자인가」 — 두 판정을 한 곳에서 (#559, spec #558).

**왜 둘인가 — ADR-0055.** 클래스의 강사는 여럿일 수 있고(공동 강사), 그중 **소유자**
한 명만 비용과 존폐를 진다: 채점 키·예산, 클래스 삭제, 소유권 이전, 공동 강사 내보내기
(`CONTEXT.md` 「공동 강사」). 나머지 일 — 문제·체크리스트·명단·보관·집계에서 빠지기·
실시간 신호 — 은 강사 누구에게나 같다. 그래서 `Class.instructor` 를 보던 자리를 이 둘
중 어느 질문인지로 갈라 이 모듈을 거치게 했다.

**지금은 둘 다 `Class.instructor` 하나만 본다** — 소유자 = 강사다. 공동 강사가 생기면
(#561) 「강사인가」 쪽 함수만 「소유자 또는 공동 강사」로 넓히면 되고, 부르는 자리는
그대로다. 「소유자인가」는 그 뒤에도 `Class.instructor` 다.

**짝이 넷이다** — 같은 질문을 묻는 모양이 자리마다 달라서다:

- 클래스 하나를 이미 손에 쥐었을 때: `is_instructor` / `is_owner`(참거짓), 집계에서 뺄
  사람들이 필요하면 `instructor_user_ids`(집합).
- 사람 하나로 클래스를 고를 때: `classes_taught_by` / `classes_owned_by`(쿼리셋).
- 여러 클래스를 한 쿼리에서 훑으며 「이 행의 사람이 그 행의 클래스의 강사인가」를 물을
  때(주석 달기·운영자 집계): `is_instructor_q`.

`classroom.instructor_scope`(강사 전용 라우트의 문)가 이 모듈 위에 서 있다. 이 모듈은
모델만 읽는다 — 이벤트·채점·제출 해석기·탈퇴처럼 라우트 밖에서도 부를 수 있게.

`tests/test_classroom_instructor_scope_structure.py` 가 화면 API·서비스·이벤트·채점·
제출 해석기·탈퇴에서 `instructor`/`instructor_id` 를 직접 두드리는 자리를 잡는다 —
남은 것은 소유자 자체를 뜻하는 자리(새 클래스의 소유자, 키·예산 알림의 수신자, 탈퇴
차단)뿐이고 그 테스트의 표에 이유가 있다.
"""

from __future__ import annotations

from django.db.models import F, Q, QuerySet

from .models import Class


def is_owner(class_obj: Class, user_id: int | None) -> bool:
    """이 사람이 이 클래스의 소유자인가 — 채점 키·예산·클래스 삭제를 할 수 있는 사람."""

    return user_id is not None and class_obj.instructor_id == user_id


def is_instructor(class_obj: Class, user_id: int | None) -> bool:
    """이 사람이 이 클래스의 강사인가(소유자 포함). 지금은 소유자뿐이다."""

    return user_id is not None and class_obj.instructor_id == user_id


def instructor_user_ids(class_obj: Class) -> frozenset[int]:
    """이 클래스의 강사 전원의 계정 id — 집계(달성률 분모·명단)에서 빼고, 강사용 실시간
    신호를 보낼 사람들이다. 지금은 소유자 한 명이다."""

    return frozenset({class_obj.instructor_id})


def classes_owned_by(user_id: int) -> QuerySet[Class]:
    """이 사람이 소유한 클래스."""

    return Class.objects.filter(instructor_id=user_id)


def classes_taught_by(user_id: int) -> QuerySet[Class]:
    """이 사람이 강사인 클래스(소유자 포함) — 강사 클래스 목록과 강사 전용 라우트의 문.
    지금은 소유한 클래스와 같다."""

    return Class.objects.filter(instructor_id=user_id)


def is_instructor_q(*, user: str, classroom: str = "") -> Q:
    """「`user` 가 가리키는 계정이 `classroom` 이 가리키는 클래스의 강사인가」를 한 쿼리
    안에서 묻는 `Q`. `user` 는 계정 id 필드까지의 경로(예: ``"members__user_id"``),
    `classroom` 은 Class 까지의 경로다(Class 자신이면 빈 문자열, 예: ``"classroom"``,
    ``"problem__classroom"``). 빼려면 ``exclude(is_instructor_q(...))`` 나 ``~`` 로 쓴다."""

    instructor_path = f"{classroom}__instructor_id" if classroom else "instructor_id"
    return Q(**{user: F(instructor_path)})
