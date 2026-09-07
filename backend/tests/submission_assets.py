"""제출 자료 목록(#190)을 읽는 테스트 헬퍼.

`SubmissionOut.assets`는 종류별 목록이라, "이 뷰어에게 소스가 보이는가" 같은
단언이 예전처럼 필드 하나를 보는 것으로 끝나지 않는다. 그 읽기를 한 곳에 모아
두면 스무 개 가까운 테스트 파일이 같은 리스트 컴프리헨션을 각자 다시 쓰지 않는다.

**모델을 직접 부르지 않는다** — 여기 함수는 전부 HTTP 응답 본문(dict)만 받는다
(CLAUDE.md: HTTP가 유일한 시임이다).
"""

from __future__ import annotations


def assets_of(body: dict, kind: str) -> list[dict]:
    """이 응답에 담긴 그 종류의 자료 전부."""

    return [a for a in body["assets"] if a["kind"] == kind]


def values_of(body: dict, kind: str) -> list[str]:
    return [a["value"] for a in assets_of(body, kind)]


def first_value(body: dict, kind: str) -> str | None:
    """그 종류의 첫 자료 값. 보이지 않거나 없으면 None.

    **둘을 구별하지 않는다** — 목록에서는 "안 보임"과 "없음"이 같은 모양이고
    (`submissions.schemas.SubmissionOut` 참고), 그 구별이 필요한 테스트는
    `assets_of`로 직접 센다.
    """

    values = values_of(body, kind)
    return values[0] if values else None


def demo_account_of(body: dict, value: str | None = None) -> str:
    """데모 URL 자료에 붙은 테스트 계정. `value`를 주면 그 데모의 것을 고른다."""

    for asset in assets_of(body, "demo_url"):
        if value is None or asset["value"] == value:
            return asset["test_account"]
    return ""
