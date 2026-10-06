"""강의실 채점이 그 채점을 부르는 내부 HTTP 호출의 예산 안에서 끝난다 (GlitchTip 오류 87).

강의실 채점은 Celery 워커 안에서 돌지 않는다 — `classroom.tasks.score_attempt`(즉시
채점)와 `core.tasks.run_scan`(60초 안전망 스캔) 둘 다 `core.tasks.call_internal`로
backend 의 내부 엔드포인트를 HTTP 로 부르고, 실제 채점(벤더 호출 포함)은 그 요청을
받은 gunicorn 워커 안에서 돈다. 호출부는 30초를 기다리고, 배포 compose 의 gunicorn 은
`--timeout`을 주지 않아 기본값 30초에 그 워커를 죽인다.

그런데 강의실 채점의 벤더 타임아웃은 120초다(#402, `classroom.scoring.
_CLASSROOM_SCORING_REQUEST_TIMEOUT_SECONDS`). 30초보다 느린 벤더 응답(추론 모델에서
정상이다)이 오면 워커가 채점 도중에 죽어 `ClassroomScoringAttempt`조차 남지 않는다 —
그래서 실패 한도(5회)에 영영 닿지 않고, 재시도와 매 스캔 tick 이 벤더를 다시 불러 강사
키의 비용만 나간다. prod 에서 `ReadTimeout: ... (read timeout=30)`으로 올라왔다.

이 파일은 그 조건을 HTTP 시임에서 본다: 태스크가 내부 엔드포인트를 부를 때 쓴
타임아웃과, 그 요청 안에서 채점이 벤더를 부를 때 쓴 타임아웃을 나란히 잡아, 후자가
전자 안에 (프롬프트 구성·DB 조회 여유를 남기고) 드는지 확인한다. 여유는
`core.llm_scoring._OPENAI_REQUEST_TIMEOUT_SECONDS` 주석이 잡은 10초와 같다.

재현 루프(실제 gunicorn + 느린 벤더 흉내)는 오류 87 의 티켓에 적었다.
"""

from __future__ import annotations

from urllib.parse import urlparse

from django.conf import settings
from django.test import Client

from classroom import tasks as classroom_tasks
from tests.classroom_scenarios import (
    FakeVendorResponse,
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    join_class,
    login,
    openai_success_body,
    submit_repository,
)

#: 내부 호출의 응답 예산에서 채점 밖 오버헤드(프롬프트 구성·DB 조회·소스 가져오기)에 남길
#: 몫 — `core.llm_scoring._OPENAI_REQUEST_TIMEOUT_SECONDS` 주석의 「10초 여유」.
_OVERHEAD_MARGIN_SECONDS = 10


def _route_requests(monkeypatch, item_id: int) -> dict:
    """`requests.post` 하나를 두 경계로 가른다 — `core.tasks`와 `core.llm_scoring`이 같은
    `requests` 모듈을 쓰므로 둘을 따로 monkeypatch 할 수 없다. backend 자신을 향한 호출은
    Django 테스트 클라이언트로 실제 HTTP 요청을 보내고, 그 밖(OpenAI)은 벤더 응답을 흉내낸다.
    각 호출의 `timeout`을 남긴다."""

    seen: dict = {"internal": [], "vendor": []}
    internal_client = Client()
    internal_base = settings.INTERNAL_API_BASE_URL

    class _InternalResponse:
        def __init__(self, response) -> None:
            self.status_code = response.status_code
            self._response = response

        def raise_for_status(self) -> None:
            assert self.status_code < 400, self._response.content

        def json(self):
            return self._response.json()

    def _post(url, **kwargs):
        if url.startswith(internal_base):
            seen["internal"].append(kwargs.get("timeout"))
            headers = {
                f"HTTP_{name.upper().replace('-', '_')}": value
                for name, value in (kwargs.get("headers") or {}).items()
            }
            response = internal_client.post(
                urlparse(url).path, content_type="application/json", **headers
            )
            return _InternalResponse(response)
        seen["vendor"].append(kwargs.get("timeout"))
        return FakeVendorResponse(200, openai_success_body(item_id))

    monkeypatch.setattr("requests.post", _post)
    return seen


def test_immediate_scoring_vendor_timeout_fits_inside_the_internal_call_budget(
    client, db, monkeypatch
):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(
        client, instructor["access"], class_id, required_labels=["README 가 있다"]
    )
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    monkeypatch.setattr(classroom_tasks.score_attempt, "delay", lambda *args, **kwargs: None)
    submitted = submit_repository(client, participant["access"], class_id, problem.id)

    seen = _route_requests(monkeypatch, problem.item_id)
    with force_real_scoring_adapter():
        result = classroom_tasks.score_attempt.run(submitted["id"])

    assert result["status"] == "scored", result
    [internal_timeout] = seen["internal"]
    [vendor_timeout] = seen["vendor"]
    assert vendor_timeout + _OVERHEAD_MARGIN_SECONDS <= internal_timeout, (
        f"벤더를 {vendor_timeout}초까지 기다리는 채점이 {internal_timeout}초 안에 답해야 하는 "
        "내부 호출 안에서 돈다 — 느린 벤더 응답이면 gunicorn 워커가 채점 도중 죽고 "
        "시도 기록도 남지 않는다(GlitchTip 오류 87)"
    )
