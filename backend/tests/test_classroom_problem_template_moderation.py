"""부적절한 템플릿을 신고하고 운영자가 내린다 (#320, CONTEXT.md 「강의실」).

핵심 대상: 자기 템플릿은 신고 대상이 아니다(내리면 된다). 같은 사람이 여러
번 신고해도 한 건이다. 운영자가 신고 목록을 보고 내리거나 기각할 수 있고,
둘 다 누가·언제·왜가 기록으로 남는다. 내려도 이미 가져간 사람의 문제는
그대로다. 운영자가 아니면 이 화면과 API에 닿을 수 없다.
"""

from __future__ import annotations

from django.core.management import call_command
from django.test import Client

from classroom.models import ProblemTemplate, ProblemTemplateModerationDecision

CLASSES_URL = "/api/classroom/classes"
TEMPLATES_URL = "/api/classroom/problem-templates"
OPERATOR_REPORTED_URL = "/api/operator/classroom/problem-templates/reported"
OPERATOR_ORIGIN = "http://testserver"


def _login(client, uid="instructor-1", email=None):
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _operator_client(username="operator-1", *, superuser=False):
    call_command("create_operator", username, password="operator-pw-9134-xyz", superuser=superuser)
    operator = Client()
    response = operator.post(
        "/api/operator/login",
        data={"username": username, "password": "operator-pw-9134-xyz"},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert response.status_code == 200, response.content
    return operator


def _moderate(operator, template_id, **payload):
    return operator.post(
        f"/api/operator/classroom/problem-templates/{template_id}/moderate",
        data=payload,
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )


def _create_class(client, access: str, name: str = "웹 스터디") -> int:
    response = client.post(
        CLASSES_URL,
        data={"name": name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_problem(client, access: str, class_id: int, title: str = "1주차") -> int:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": title, "description": "설명", "submission_format": "source"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _publish(client, access: str, class_id: int, problem_id: int, publisher_display_name="김강사"):
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/publish-template",
        data={"publisher_display_name": publisher_display_name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()


def _report(client, access: str, share_code: str, reason="부적절한 내용입니다."):
    return client.post(
        f"{TEMPLATES_URL}/{share_code}/report",
        data={"reason": reason},
        content_type="application/json",
        **_auth_header(access),
    )


def test_owner_cannot_report_their_own_template(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)
    share_code = _publish(client, pair["access"], class_id, problem_id)["share_code"]

    response = _report(client, pair["access"], share_code)
    assert response.status_code == 403


def test_reporting_twice_counts_as_one(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    problem_id = _create_problem(client, a["access"], class_id)
    template = _publish(client, a["access"], class_id, problem_id)
    share_code = template["share_code"]

    first = _report(client, b["access"], share_code, "사유1")
    second = _report(client, b["access"], share_code, "사유2")
    assert first.status_code == 201
    assert second.status_code == 201

    operator = _operator_client()
    reported = operator.get(OPERATOR_REPORTED_URL)
    row = next(r for r in reported.json() if r["id"] == template["id"])
    assert row["report_count"] == 1


def test_operator_sees_content_reasons_and_count(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    c = _login(client, uid="instructor-c")
    class_id = _create_class(client, a["access"])
    problem_id = _create_problem(client, a["access"], class_id, "부적절한 문제")
    template = _publish(client, a["access"], class_id, problem_id, "나쁜강사")
    share_code = template["share_code"]

    _report(client, b["access"], share_code, "저작권 침해")
    _report(client, c["access"], share_code, "스팸")

    operator = _operator_client()
    reported = operator.get(OPERATOR_REPORTED_URL)
    assert reported.status_code == 200
    row = next(r for r in reported.json() if r["id"] == template["id"])
    assert row["title"] == "부적절한 문제"
    assert row["publisher_display_name"] == "나쁜강사"
    assert row["report_count"] == 2
    assert set(row["report_reasons"]) == {"저작권 침해", "스팸"}


def test_operator_takes_down_a_reported_template(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    problem_id = _create_problem(client, a["access"], class_id)
    template = _publish(client, a["access"], class_id, problem_id)
    share_code = template["share_code"]
    _report(client, b["access"], share_code)

    operator = _operator_client("op-taker")
    response = _moderate(operator, template["id"], decision="takedown", note="약관 위반으로 내립니다.")
    assert response.status_code == 200, response.content
    assert response.json()["taken_down"] is True

    # 올린 사람 본인에게는 내려간 뒤에도 보인다(#316) — 남에게는 404다.
    preview_owner = client.get(f"{TEMPLATES_URL}/{share_code}", **_auth_header(a["access"]))
    assert preview_owner.status_code == 200
    assert preview_owner.json()["taken_down"] is True
    preview_other = client.get(f"{TEMPLATES_URL}/{share_code}", **_auth_header(b["access"]))
    assert preview_other.status_code == 404

    decision = ProblemTemplateModerationDecision.objects.get(template_id=template["id"])
    assert decision.decision == ProblemTemplateModerationDecision.Decision.TAKEDOWN
    assert decision.note == "약관 위반으로 내립니다."
    assert decision.decided_by.username == "op-taker"
    assert decision.decided_at is not None


def test_operator_can_dismiss_a_report(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    problem_id = _create_problem(client, a["access"], class_id)
    template = _publish(client, a["access"], class_id, problem_id)
    _report(client, b["access"], template["share_code"], "근거 없는 신고")

    operator = _operator_client("op-dismisser")
    response = _moderate(operator, template["id"], decision="dismiss", note="신고 근거가 부족합니다.")
    assert response.status_code == 200
    assert response.json()["taken_down"] is False

    decision = ProblemTemplateModerationDecision.objects.get(template_id=template["id"])
    assert decision.decision == ProblemTemplateModerationDecision.Decision.DISMISS
    assert decision.note == "신고 근거가 부족합니다."

    # 기각된 신고는 다시 대기열에 뜨지 않는다.
    reported = operator.get(OPERATOR_REPORTED_URL)
    assert template["id"] not in [r["id"] for r in reported.json()]

    # 그리고 템플릿은 여전히 공개 중이다.
    still_there = client.get(f"{TEMPLATES_URL}/{template['share_code']}", **_auth_header(a["access"]))
    assert still_there.status_code == 200


def test_moderation_response_carries_the_real_checklist(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    problem_id = _create_problem(client, a["access"], class_id)
    client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": "테스트가 통과한다", "required": True},
        content_type="application/json",
        **_auth_header(a["access"]),
    )
    template = _publish(client, a["access"], class_id, problem_id)
    _report(client, b["access"], template["share_code"])

    operator = _operator_client()
    response = _moderate(operator, template["id"], decision="dismiss", note="근거 부족")
    assert [i["label"] for i in response.json()["checklist_items"]] == ["테스트가 통과한다"]


def test_moderation_requires_a_note(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    problem_id = _create_problem(client, a["access"], class_id)
    template = _publish(client, a["access"], class_id, problem_id)
    _report(client, b["access"], template["share_code"])

    operator = _operator_client()
    response = _moderate(operator, template["id"], decision="takedown", note="   ")
    assert response.status_code == 422


def test_a_new_report_after_dismissal_reopens_the_queue(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    c = _login(client, uid="instructor-c")
    class_id = _create_class(client, a["access"])
    problem_id = _create_problem(client, a["access"], class_id)
    template = _publish(client, a["access"], class_id, problem_id)
    share_code = template["share_code"]
    _report(client, b["access"], share_code, "첫 신고")

    operator = _operator_client()
    _moderate(operator, template["id"], decision="dismiss", note="근거 부족")

    reported_after_dismiss = operator.get(OPERATOR_REPORTED_URL)
    assert template["id"] not in [r["id"] for r in reported_after_dismiss.json()]

    _report(client, c["access"], share_code, "두번째 신고")
    reported_after_new_report = operator.get(OPERATOR_REPORTED_URL)
    assert template["id"] in [r["id"] for r in reported_after_new_report.json()]


def test_takedown_does_not_affect_already_imported_problems(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    problem_id = _create_problem(client, a["access"], class_id, "부적절한 문제")
    template = _publish(client, a["access"], class_id, problem_id)
    share_code = template["share_code"]

    target_class = _create_class(client, b["access"])
    imported = client.post(
        f"{TEMPLATES_URL}/{share_code}/import",
        data={"target_class_id": target_class},
        content_type="application/json",
        **_auth_header(b["access"]),
    ).json()

    _report(client, b["access"], share_code)
    operator = _operator_client()
    _moderate(operator, template["id"], decision="takedown", note="내립니다.")

    still_there = client.get(
        f"{CLASSES_URL}/{target_class}/problems/{imported['id']}", **_auth_header(b["access"])
    )
    assert still_there.status_code == 200


def test_non_operator_cannot_reach_the_operator_surface(client, db):
    _login(client)
    response = client.get(OPERATOR_REPORTED_URL)
    assert response.status_code == 401


def test_non_staff_operator_session_is_forbidden(client, db):
    # 세션은 있지만 운영자가 아닌 계정 — 401이 아니라 403이어야 한다
    # (test_ledger.py의 같은 이름 테스트와 같은 관용구).
    from django.contrib.auth import get_user_model

    get_user_model().objects.create_user(
        username="not-an-operator", password="not-an-operator-pw", is_staff=False
    )
    assert client.login(username="not-an-operator", password="not-an-operator-pw")

    response = client.get(OPERATOR_REPORTED_URL)
    assert response.status_code == 403
