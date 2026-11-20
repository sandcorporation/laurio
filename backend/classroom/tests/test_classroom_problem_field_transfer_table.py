"""복사·템플릿이 옮기는 Problem 필드는 표 하나가 정한다 (#441, 부모 #432).

여섯 경로(문제 복사, 클래스 복사, 문제 템플릿 공개·가져오기, 클래스 템플릿
공개·가져오기)가 전부 `classroom.services.PROBLEM_FIELD_TRANSFER_TABLE`을
거쳐 값을 옮긴다. 옮기는 규칙은 지금 그대로다: 채점 모델은 복사 때만,
추론 강도는 어디서도, 나머지 설정(형식·채점 지침·문법 검사)은 모두.

**구조 검사**(아래 `test_every_problem_field_is_declared_in_the_table`)는
`Problem`의 구체 필드가 모두 표에 적혀 있는지를 모델 메타로 확인한다 —
`tests/test_app_boundaries.py`와 같은 종류로, HTTP 시임 규칙(CLAUDE.md
「HTTP가 유일한 시임이다」)의 예외다. 나머지는 전부 마운트된 HTTP API로
확인한다."""

from __future__ import annotations

from classroom import services
from classroom.models import Class, Problem, ProblemTemplate
from tests.classroom_scenarios import (
    CLASSES_URL,
    auth_header,
    create_class,
    create_open_problem,
    login,
)

PROBLEM_TEMPLATES_URL = "/api/classroom/problem-templates"
CLASS_TEMPLATES_URL = "/api/classroom/class-templates"


# --- 구조 검사 -------------------------------------------------------------


def test_every_problem_field_is_declared_in_the_table():
    """`Problem`에 필드를 더하고 표에 적지 않으면 이 테스트가 빨개진다(#441 AC)."""

    concrete_field_names = {f.name for f in Problem._meta.get_fields() if f.concrete}
    table_field_names = {rule.field for rule in services.PROBLEM_FIELD_TRANSFER_TABLE}
    missing = concrete_field_names - table_field_names
    assert not missing, f"표에 적지 않은 Problem 필드: {sorted(missing)}"

    extra = table_field_names - concrete_field_names
    assert not extra, f"표에는 있지만 Problem에는 없는 필드: {sorted(extra)}"


def test_fields_the_table_says_it_does_not_move_are_marked_so():
    """식별자·시각·상태·거부 시각처럼 옮기지 않는 필드는 표에 「옮기지 않음」
    (copies=False, templates=False)으로 명시돼 있다(#441 AC)."""

    never_moved = {"id", "classroom", "status", "order", "scoring_model_rejected_at", "created_at", "updated_at"}
    by_name = {rule.field: rule for rule in services.PROBLEM_FIELD_TRANSFER_TABLE}
    for name in never_moved:
        rule = by_name[name]
        assert rule.copies is False, f"{name}은 옮기지 않아야 하는데 copies=True다"
        assert rule.templates is False, f"{name}은 옮기지 않아야 하는데 templates=True다"


# --- 여섯 경로: 옮기는 것들 ------------------------------------------------


def test_problem_copy_moves_format_guideline_syntax_check_and_model(client, db):
    access = login(client)["access"]
    source_class = create_class(client, access, name="1기")
    target_class = create_class(client, access, name="2기")
    problem = create_open_problem(
        client,
        access,
        source_class,
        submission_formats=["source"],
        model="gpt-4.1-mini",
        reasoning_effort="low",
        syntax_check_enabled=False,
    )

    response = client.post(
        f"{CLASSES_URL}/{source_class}/problems/{problem.id}/copy",
        data={"target_class_id": target_class},
        content_type="application/json",
        **auth_header(access),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["submission_formats"] == ["source"]
    assert body["model"] == "gpt-4.1-mini"
    assert body["syntax_check_enabled"] is False
    assert body["status"] == Problem.Status.DRAFT
    # 추론 강도는 복사·템플릿 어디서도 옮기지 않는다.
    assert body["reasoning_effort"] == ""


def test_class_copy_moves_each_problems_model_and_syntax_check(client, db):
    access = login(client)["access"]
    source_class = create_class(client, access, name="1기")
    problem = create_open_problem(
        client,
        access,
        source_class,
        submission_formats=["repository"],
        model="gpt-4.1-mini",
        reasoning_effort="high",
        syntax_check_enabled=False,
    )

    response = client.post(
        f"{CLASSES_URL}/{source_class}/copy", content_type="application/json", **auth_header(access)
    )

    assert response.status_code == 201
    new_class_id = response.json()["id"]
    copied = Class.objects.get(pk=new_class_id).problems.get()
    assert copied.submission_formats == ["repository"]
    assert copied.model == "gpt-4.1-mini"
    assert copied.syntax_check_enabled is False
    assert copied.status == Problem.Status.DRAFT
    assert copied.reasoning_effort == ""
    assert copied.pk != problem.id


def test_problem_template_publish_and_import_do_not_move_model_or_reasoning_effort(client, db):
    access = login(client)["access"]
    source_class = create_class(client, access, name="1기")
    target_class = create_class(client, access, name="2기")
    problem = create_open_problem(
        client,
        access,
        source_class,
        submission_formats=["source", "repository"],
        model="gpt-4.1-mini",
        reasoning_effort="low",
        syntax_check_enabled=False,
    )

    published = client.post(
        f"{CLASSES_URL}/{source_class}/problems/{problem.id}/publish-template",
        data={"publisher_display_name": "김강사"},
        content_type="application/json",
        **auth_header(access),
    )
    assert published.status_code == 201, published.content
    share_code = published.json()["share_code"]

    # 템플릿 사본 자체에도 채점 모델·추론 강도를 담을 필드가 없다.
    assert not hasattr(ProblemTemplate, "model")
    template_body = published.json()
    assert template_body["submission_formats"] == ["source", "repository"]
    assert template_body["syntax_check_enabled"] is False

    imported = client.post(
        f"{PROBLEM_TEMPLATES_URL}/{share_code}/import",
        data={"target_class_id": target_class},
        content_type="application/json",
        **auth_header(access),
    )
    assert imported.status_code == 201, imported.content
    body = imported.json()
    assert body["submission_formats"] == ["source", "repository"]
    assert body["syntax_check_enabled"] is False
    assert body["model"] == ""
    assert body["reasoning_effort"] == ""
    assert body["status"] == Problem.Status.DRAFT


def test_class_template_publish_and_import_do_not_move_model_or_reasoning_effort(client, db):
    access = login(client)["access"]
    source_class = create_class(client, access, name="1기")
    create_open_problem(
        client,
        access,
        source_class,
        submission_formats=["source"],
        model="gpt-4.1-mini",
        reasoning_effort="medium",
        syntax_check_enabled=False,
    )

    published = client.post(
        f"{CLASSES_URL}/{source_class}/publish-template",
        data={"publisher_display_name": "김강사"},
        content_type="application/json",
        **auth_header(access),
    )
    assert published.status_code == 201, published.content
    share_code = published.json()["share_code"]
    template_problem = published.json()["problems"][0]
    assert template_problem["submission_formats"] == ["source"]
    assert template_problem["syntax_check_enabled"] is False

    imported = client.post(
        f"{CLASS_TEMPLATES_URL}/{share_code}/import",
        data={"name": "가져온 클래스"},
        content_type="application/json",
        **auth_header(access),
    )
    assert imported.status_code == 201, imported.content
    new_class_id = imported.json()["id"]
    problem = Class.objects.get(pk=new_class_id).problems.get()
    assert problem.submission_formats == ["source"]
    assert problem.syntax_check_enabled is False
    assert problem.model == ""
    assert problem.reasoning_effort == ""
    assert problem.status == Problem.Status.DRAFT


def test_checklist_and_order_still_follow_every_path(client, db):
    """체크리스트·순서는 필드 표 밖의 일이지만(#441 AC), 여섯 경로 모두 여전히
    옮긴다는 것을 이 표 티켓의 테스트도 한 번 더 고정해 둔다."""

    access = login(client)["access"]
    source_class = create_class(client, access, name="1기")
    target_class = create_class(client, access, name="2기")
    first = create_open_problem(client, access, source_class, title="1주차", required_labels=["항목 A"])
    second = create_open_problem(client, access, source_class, title="2주차", required_labels=["항목 B"])

    response = client.post(
        f"{CLASSES_URL}/{source_class}/problems/{first.id}/copy",
        data={"target_class_id": target_class},
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == 201
    body = response.json()
    assert [item["label"] for item in body["checklist_items"]] == ["항목 A"]

    class_copy = client.post(
        f"{CLASSES_URL}/{source_class}/copy", content_type="application/json", **auth_header(access)
    )
    assert class_copy.status_code == 201
    copied_problems = list(Class.objects.get(pk=class_copy.json()["id"]).problems.order_by("order", "id"))
    assert [p.title for p in copied_problems] == ["1주차", "2주차"]
    assert [list(p.checklist_items.values_list("label", flat=True)) for p in copied_problems] == [
        ["항목 A"],
        ["항목 B"],
    ]
