"""문법 검사 기본 항목을 강사가 문제마다 끈다 — 복사·템플릿이 설정을 옮긴다
(#410, CONTEXT.md 「문법 검사」).

핵심 대상: 문제 만들기·편집 API로 켜고 끄고, 끈 문제는 새 시도 판정·통과·
달성률에서 그 항목이 빠진다. 켜고 꺼도 이미 매긴 판정은 조회에서 그대로다
(ADR-0006). 문제·클래스 복사와 템플릿 공개·가져오기가 설정을 그대로
옮긴다.
"""

from __future__ import annotations

from django.conf import settings
from django.test import override_settings

CLASSES_URL = "/api/classroom/classes"
SCAN_URL = "/api/internal/scans/classroom-submission-scoring"


def _internal_headers() -> dict:
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


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


def _create_class(client, access: str, name: str = "웹 스터디") -> int:
    response = client.post(
        CLASSES_URL,
        data={"name": name, "instructor_display_name": "강사"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _set_key(client, access: str, class_id: int) -> None:
    response = client.put(
        f"{CLASSES_URL}/{class_id}/openai-key",
        data={"api_key": "sk-test-instructor-key"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


def _join_code(client, access: str, class_id: int) -> str:
    detail = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(access))
    assert detail.status_code == 200
    return detail.json()["join_code"]


def _join(client, access: str, join_code: str) -> None:
    response = client.post(
        f"/api/classroom/join/{join_code}",
        data={"display_name": "참여자"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


def _run_scan(client) -> dict:
    response = client.post(SCAN_URL, content_type="application/json", **_internal_headers())
    assert response.status_code == 200, response.content
    return response.json()


def test_new_problem_defaults_to_enabled_and_create_api_can_turn_it_off(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])

    default_created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "기본값", "submission_formats": ["repository"]},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert default_created.status_code == 201
    assert default_created.json()["syntax_check_enabled"] is True

    turned_off = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={
            "title": "의사코드 문제",
            "submission_formats": ["repository"],
            "syntax_check_enabled": False,
        },
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert turned_off.status_code == 201
    assert turned_off.json()["syntax_check_enabled"] is False


def test_edit_api_toggles_the_base_item(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": ["repository"]},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    problem_id = created.json()["id"]
    assert created.json()["syntax_check_enabled"] is True

    turned_off = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"syntax_check_enabled": False},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert turned_off.status_code == 200
    assert turned_off.json()["syntax_check_enabled"] is False

    # 필드를 생략하면 바꾸지 않는다 — 기존 PATCH 관례.
    unchanged = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"title": "1주차(수정)"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert unchanged.status_code == 200
    assert unchanged.json()["syntax_check_enabled"] is False

    turned_on = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"syntax_check_enabled": True},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert turned_on.status_code == 200
    assert turned_on.json()["syntax_check_enabled"] is True


def _setup_disabled_problem(client) -> dict:
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={
            "title": "의사코드",
            "submission_formats": ["repository"],
            "syntax_check_enabled": False,
        },
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    problem_id = created.json()["id"]
    checklist = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": "print가 있다", "required": True},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    item_id = checklist.json()["id"]
    client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    with override_settings(
        GITHUB_FAKE_REPO_FILES={
            "https://github.com/octocat/pseudo-code": {"app.py": "이것은 진짜 파이썬이 아니다 print가 있다"}
        }
    ):
        submitted = client.post(
            f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions",
            data={"value": "https://github.com/octocat/pseudo-code", "submission_format": "repository"},
            content_type="application/json",
            **_auth_header(participant["access"]),
        )
    assert submitted.status_code == 201, submitted.content
    return {
        "instructor": instructor,
        "participant": participant,
        "class_id": class_id,
        "problem_id": problem_id,
        "item_id": item_id,
        "submission_id": submitted.json()["id"],
    }


def _run_scan_for_pseudo_code(client) -> dict:
    with override_settings(
        GITHUB_FAKE_REPO_FILES={
            "https://github.com/octocat/pseudo-code": {"app.py": "이것은 진짜 파이썬이 아니다 print가 있다"}
        }
    ):
        return _run_scan(client)


def test_disabled_base_item_is_absent_from_the_new_attempts_verdict_and_passes(client, db):
    """끈 문제의 새 시도 판정에 기본 항목이 없고, 통과·달성률에서 빠진다
    (#410 AC) — 실제로는 문법 오류가 있을 수도 있는 소스지만(의사코드), 꺼
    두었으니 통과를 막지 않는다."""

    ctx = _setup_disabled_problem(client)

    _run_scan_for_pseudo_code(client)

    mine = client.get(
        f"{CLASSES_URL}/{ctx['class_id']}/problems/{ctx['problem_id']}/mine",
        **_auth_header(ctx["participant"]["access"]),
    ).json()
    submission_out = mine["submissions"][0]
    assert submission_out["score"]["syntax_check"] is None
    assert submission_out["passed"] is True

    problems = client.get(
        f"{CLASSES_URL}/{ctx['class_id']}/problems", **_auth_header(ctx["instructor"]["access"])
    ).json()
    problem = next(p for p in problems if p["id"] == ctx["problem_id"])
    assert problem["passed_count"] == 1


def test_toggling_after_scoring_does_not_change_the_recorded_verdict_but_changes_pass_status(
    client, db
):
    """켜고 꺼도 이미 매긴 판정은 조회에서 그대로다(ADR-0006) — 통과 여부만
    지금 설정으로 다시 셈된다(#410 AC)."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": ["repository"]},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    problem_id = created.json()["id"]
    client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": "print가 있다", "required": True},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    bad_url = "https://github.com/octocat/broken-indent"
    with override_settings(
        GITHUB_FAKE_REPO_FILES={bad_url: {"app.py": "def f():\n    x = 1\n        return x  # print가 있다\n"}}
    ):
        submitted = client.post(
            f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions",
            data={"value": bad_url, "submission_format": "repository"},
            content_type="application/json",
            **_auth_header(participant["access"]),
        )
        assert submitted.status_code == 201
        _run_scan(client)

    mine_before = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/mine", **_auth_header(participant["access"])
    ).json()
    submission_before = mine_before["submissions"][0]
    assert submission_before["score"]["syntax_check"]["is_met"] is False
    assert submission_before["passed"] is False

    off = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"syntax_check_enabled": False},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert off.status_code == 200

    mine_after = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/mine", **_auth_header(participant["access"])
    ).json()
    submission_after = mine_after["submissions"][0]
    # 저장된 판정 자체(reasoning/syntax_check)는 바뀌지 않는다.
    assert submission_after["score"]["syntax_check"] == submission_before["score"]["syntax_check"]
    # 통과 여부는 지금 설정(꺼짐)으로 다시 셈되어 뒤집힌다.
    assert submission_after["passed"] is True


def test_problem_copy_carries_the_setting(client, db):
    instructor = _login(client, uid="instructor-1")
    source_class_id = _create_class(client, instructor["access"], name="원본 클래스")
    target_class_id = _create_class(client, instructor["access"], name="대상 클래스")
    created = client.post(
        f"{CLASSES_URL}/{source_class_id}/problems",
        data={
            "title": "의사코드",
            "submission_formats": ["repository"],
            "syntax_check_enabled": False,
        },
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    problem_id = created.json()["id"]

    copied = client.post(
        f"{CLASSES_URL}/{source_class_id}/problems/{problem_id}/copy",
        data={"target_class_id": target_class_id},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert copied.status_code == 201
    assert copied.json()["syntax_check_enabled"] is False


def test_class_copy_carries_the_setting(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={
            "title": "의사코드",
            "submission_formats": ["repository"],
            "syntax_check_enabled": False,
        },
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    copied = client.post(
        f"{CLASSES_URL}/{class_id}/copy", content_type="application/json", **_auth_header(instructor["access"])
    )
    assert copied.status_code == 201
    new_class_id = copied.json()["id"]

    problems = client.get(
        f"{CLASSES_URL}/{new_class_id}/problems", **_auth_header(instructor["access"])
    ).json()
    assert problems[0]["syntax_check_enabled"] is False


def test_problem_template_publish_and_import_carry_the_setting(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={
            "title": "의사코드",
            "submission_formats": ["repository"],
            "syntax_check_enabled": False,
        },
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    problem_id = created.json()["id"]

    published = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/publish-template",
        data={"publisher_display_name": "강사"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert published.status_code == 201
    template = published.json()
    # 템플릿 미리보기에 켜짐 여부가 보인다(#410 AC).
    assert template["syntax_check_enabled"] is False
    share_code = template["share_code"]

    other_class_id = _create_class(client, instructor["access"], name="다른 클래스")
    imported = client.post(
        f"/api/classroom/problem-templates/{share_code}/import",
        data={"target_class_id": other_class_id},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert imported.status_code == 201
    assert imported.json()["syntax_check_enabled"] is False


def test_class_template_publish_and_import_carry_the_setting(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={
            "title": "의사코드",
            "submission_formats": ["repository"],
            "syntax_check_enabled": False,
        },
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    published = client.post(
        f"{CLASSES_URL}/{class_id}/publish-template",
        data={"publisher_display_name": "강사"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert published.status_code == 201
    template = published.json()
    assert template["problems"][0]["syntax_check_enabled"] is False
    share_code = template["share_code"]

    imported = client.post(
        f"/api/classroom/class-templates/{share_code}/import",
        data={"name": "가져온 클래스"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert imported.status_code == 201
    new_class_id = imported.json()["id"]

    problems = client.get(
        f"{CLASSES_URL}/{new_class_id}/problems", **_auth_header(instructor["access"])
    ).json()
    assert problems[0]["syntax_check_enabled"] is False


def test_unknown_type_for_syntax_check_enabled_is_rejected(client, db):
    """스키마 검증 — 불리언으로 해석할 수 없는 값을 보내면 422다."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={
            "title": "1주차",
            "submission_formats": ["repository"],
            "syntax_check_enabled": "banana",
        },
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 422
