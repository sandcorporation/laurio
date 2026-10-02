"""제출하면 바로 채점에 들어간다 — 시도마다 Score 하나 (#287, CONTEXT.md
「강의실」, ADR-0006/0031/0037/0039).

핵심 대상: 제출 즉시 사람이 더 할 일 없이 채점이 비동기로 시작되고(스캔이
집는다), 시도마다 `ClassroomScore`가 정확히 하나 생기며 다시 채점되지
않는다. 강사 본인의 키와 그 문제의 모델로 친다. 채점이 실패해도 무한히
되돌지 않고 상한(5회) 뒤에는 그 사실이 판정으로 남는다. 키가 없거나
틀렸을 때 참여자가 보는 것이 「고장」으로 읽히지 않는다.

**이 파일은 `OpenAIScoringAdapter` 경로 자체를 검증한다**(HTTP 상태·응답
모양별 분기) — 그래서 모든 테스트가 `CLASSROOM_SCORING_ADAPTER_MODE`를 그
어댑터로 강제한다(#340, ADR-0043). 기본값(fake)이 되는 `FakeClassroomScoringAdapter`
경로는 별도 파일(`test_classroom_scoring_fake_adapter.py`)이 덮는다 —
"결정적이고 네트워크가 없다"는 이 파일의 관심사가 아니다.

**공용 시나리오 빌더(#433) 위로 옮겼다** — `tests/classroom_scenarios.py` 참고.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from classroom.models import ClassroomScore, ClassroomScoringAttempt, ClassroomSubmission
from notifications.models import Notification, NotificationType
from tests.classroom_scenarios import (
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    join_class,
    login,
    mine,
    respond_with_key_rejection,
    respond_with_permanent_failure,
    respond_with_transient_failure,
    respond_with_verdict,
    run_scan,
    submit_repository,
    submit_source,
    user_id,
)


@pytest.fixture(autouse=True)
def _force_real_scoring_adapter():
    with force_real_scoring_adapter():
        yield


def _setup_submission(client, *, submission_format="repository", with_key=True):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"], with_key=with_key)
    problem = create_open_problem(client, instructor["access"], class_id, submission_formats=[submission_format])
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submitted = submit_repository(client, participant["access"], class_id, problem.id)
    return {
        "instructor": instructor,
        "participant": participant,
        "class_id": class_id,
        "problem_id": problem.id,
        "item_id": problem.item_id,
        "submission_id": submitted["id"],
    }


def test_submitting_does_not_score_synchronously(client, db):
    ctx = _setup_submission(client)

    mine_out = mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])

    assert mine_out["submissions"][0]["status"] == "pending"
    assert ClassroomScore.objects.count() == 0


def test_scan_scores_a_submission_with_a_key(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_verdict(monkeypatch, ctx["item_id"], is_met=True)

    result = run_scan(client)

    assert result["count"] == 1
    assert ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()
    mine_out = mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    submission_out = mine_out["submissions"][0]
    assert submission_out["status"] == "scored"
    assert submission_out["score"]["reasoning"] == [
        {"checklist_item_id": ctx["item_id"], "is_met": True, "reasoning": "판정 근거"}
    ]


def test_scoring_asks_the_model_to_write_reasoning_in_korean(client, db, monkeypatch):
    # 소스가 영어라 지시가 없으면 실물 모델이 근거를 영어로 쓴다 — 참여자 화면에
    # 그대로 나가는 문장이다. 벤더로 나가는 요청 자체에 그 지시가 실렸는지 본다.
    ctx = _setup_submission(client)
    sent: list = []
    respond_with_verdict(monkeypatch, ctx["item_id"], is_met=True, capture=sent)

    run_scan(client)

    messages = {m["role"]: m["content"] for m in sent[0]["messages"]}
    assert "한국어" in messages["user"]
    assert "공모전" not in messages["system"]
    assert "한국어" in ClassroomScore.objects.get(submission_id=ctx["submission_id"]).prompt


def test_scan_skips_a_submission_whose_class_has_no_key(client, db, monkeypatch):
    called: list = []
    respond_with_verdict(monkeypatch, 0, capture=called)
    ctx = _setup_submission(client, with_key=False)

    result = run_scan(client)

    assert result["count"] == 0
    assert not called
    assert ClassroomScore.objects.count() == 0
    assert ClassroomScoringAttempt.objects.count() == 0
    mine_out = mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    assert mine_out["submissions"][0]["status"] == "pending"


def test_score_is_created_exactly_once_even_if_scanned_twice(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_verdict(monkeypatch, ctx["item_id"], is_met=True)

    run_scan(client)
    second = run_scan(client)

    assert second["count"] == 0
    assert ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).count() == 1


def test_wrong_key_does_not_finalize_a_score_it_waits_for_a_new_key(client, db, monkeypatch):
    """#355 이전에는 401이 즉시 전체 미달 `ClassroomScore`로 굳었다 — 강사의
    오타 하나가 참여자에게 영구 0%가 되는 길이었다. 이제는 `ClassroomScore`를
    만들지 않고, 그 클래스의 채점 키 상태만 "거부됨"으로 바꾼다(자세한
    검증은 `test_classroom_scoring_key_rejection.py`)."""

    ctx = _setup_submission(client)
    respond_with_key_rejection(monkeypatch, status_code=401, message="Incorrect API key")

    run_scan(client)

    assert not ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()
    mine_out = mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    submission_out = mine_out["submissions"][0]
    assert submission_out["status"] == "pending"
    assert submission_out["pending_reason"] == "no_api_key"


def test_non_auth_permanent_failure_still_finalizes_immediately(client, db, monkeypatch):
    """#355이 건드리지 않은 경로를 고정한다 — 401·403 **밖의** 영구 실패
    (여기서는 잘린 응답, finish_reason != "stop")는 지금과 똑같이 유예 없이
    즉시 전체 미달로 끝난다."""

    ctx = _setup_submission(client)
    respond_with_permanent_failure(monkeypatch)

    run_scan(client)

    score = ClassroomScore.objects.get(submission_id=ctx["submission_id"])
    assert score.model_version != "gpt-4o-mini-2024-07-18"
    assert ClassroomScoringAttempt.objects.filter(submission_id=ctx["submission_id"], permanent=True).exists()


def test_transient_failures_retry_up_to_the_cap_then_finalize(client, db, monkeypatch):
    ctx = _setup_submission(client)
    submission = ClassroomSubmission.objects.get(id=ctx["submission_id"])
    for _ in range(4):
        ClassroomScoringAttempt.objects.create(submission=submission, error="네트워크 순단", permanent=False)

    respond_with_transient_failure(monkeypatch, status_code=500, message="internal error")

    run_scan(client)

    assert ClassroomScoringAttempt.objects.filter(submission=submission).count() == 5
    score = ClassroomScore.objects.get(submission=submission)
    assert score.reasoning[0]["is_met"] is False


def test_repository_submission_is_scored_from_the_cloned_source(client, db, monkeypatch):
    ctx = _setup_submission(client, submission_format="repository")
    captured_prompts: list = []
    respond_with_verdict(monkeypatch, ctx["item_id"], is_met=True, capture=captured_prompts)

    run_scan(client)

    assert len(captured_prompts) == 1
    assert "app.py" in captured_prompts[0]["messages"][1]["content"]


def test_score_appears_in_the_scan_result_rows(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_verdict(monkeypatch, ctx["item_id"], is_met=True)

    result = run_scan(client)

    assert result["rows"][0]["status"] == "scored"
    assert result["rows"][0]["submission_id"] == ctx["submission_id"]


def test_source_submission_is_scored_from_the_uploaded_object(client, db, monkeypatch):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, submission_formats=["source"])
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submitted = submit_source(
        client,
        participant["access"],
        class_id,
        problem.id,
        participant_user_id=user_id("participant-1"),
        files={"main.py": "SOURCE_MARKER\n"},
    )

    captured_prompts: list = []
    respond_with_verdict(monkeypatch, problem.item_id, is_met=True, capture=captured_prompts)

    result = run_scan(client)

    assert result["count"] == 1
    assert "SOURCE_MARKER" in captured_prompts[0]["messages"][1]["content"]
    score = ClassroomScore.objects.get(submission_id=submitted["id"])
    assert score.reasoning == [{"checklist_item_id": problem.item_id, "is_met": True, "reasoning": "판정 근거"}]


def test_text_files_outside_code_extensions_reach_the_model_but_known_noise_does_not(
    client, db, monkeypatch
):
    """소스 선별은 허용 목록이 아니라 차단 목록이다(2026-10-02) — 읽히는 텍스트는
    기본으로 채점에 들어가고, 예산만 먹는 것으로 알려진 파일만 빠진다.

    계기는 Packet Tracer 과제다: 장비 설정(`show running-config`)을 `.txt` 로
    묶어 내면 예전 허용 목록에 `.txt` 가 없어 채점자가 빈 소스를 받았다.
    `Dockerfile`·`README`(확장자 없음)도 같은 이유로 빠졌었다."""

    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, submission_formats=["source"])
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submit_source(
        client,
        participant["access"],
        class_id,
        problem.id,
        participant_user_id=user_id("participant-1"),
        files={
            "configs/R1.txt": "hostname R1 CONFIG_TXT_MARKER\n",
            "configs/SW1.cfg": "hostname SW1 CONFIG_CFG_MARKER\n",
            "Dockerfile": "FROM python DOCKERFILE_MARKER\n",
            "README": "README_MARKER\n",
            "package-lock.json": "LOCKFILE_TRAP_MARKER",
            "static/app.min.js": "MINIFIED_TRAP_MARKER",
            "static/app.js.map": "SOURCEMAP_TRAP_MARKER",
            "logo.png": "IMAGE_TRAP_MARKER",
            # 맥에서 만든 zip 에 섞이는 메타데이터 — NUL 바이트도 UTF-8 로는
            # 유효해서, 허용 목록이 우연히 막아 주던 것을 이제 따로 막아야 한다.
            "__MACOSX/configs/._R1.txt": "\x00\x05\x16\x07APPLEDOUBLE_TRAP_MARKER",
            "notes.bin": "\x00\x00NUL_BINARY_TRAP_MARKER",
        },
    )

    captured_prompts: list = []
    respond_with_verdict(monkeypatch, problem.item_id, is_met=True, capture=captured_prompts)

    run_scan(client)

    prompt = captured_prompts[0]["messages"][1]["content"]
    for marker in ("CONFIG_TXT_MARKER", "CONFIG_CFG_MARKER", "DOCKERFILE_MARKER", "README_MARKER"):
        assert marker in prompt
    for trap in (
        "LOCKFILE_TRAP_MARKER",
        "MINIFIED_TRAP_MARKER",
        "SOURCEMAP_TRAP_MARKER",
        "IMAGE_TRAP_MARKER",
        "APPLEDOUBLE_TRAP_MARKER",
        "NUL_BINARY_TRAP_MARKER",
    ):
        assert trap not in prompt


def test_source_not_yet_in_storage_retries_instead_of_failing(client, db, monkeypatch):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, submission_formats=["source"])
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])

    # 스토리지에 아직 쓰지 않은 object_key — 업로드가 지연된 상황을 흉내낸다.
    submitted = submit_source(
        client,
        participant["access"],
        class_id,
        problem.id,
        participant_user_id=user_id("participant-1"),
        write_to_storage=False,
    )

    called: list = []
    respond_with_verdict(monkeypatch, problem.item_id, is_met=True, capture=called)

    result = run_scan(client)

    # 후보로는 집혔지만("아직" 상태를 남기는 것도 처리다) LLM은 부르지 않는다 —
    # 소스가 없는 채로 채점을 시도해 점수를 만들면 안 된다.
    assert result["rows"][0]["status"] == "source_not_ready"
    assert not called
    assert ClassroomScore.objects.filter(submission_id=submitted["id"]).count() == 0
    assert ClassroomScoringAttempt.objects.filter(
        submission_id=submitted["id"], permanent=False
    ).exists()


# --- 채점 완료를 낸 사람에게 알린다 (#303) --------------------------------------------


def _participant_user_id():
    return get_user_model().objects.get(username="kakao:participant-1").id


def _instructor_user_id():
    return get_user_model().objects.get(username="kakao:instructor-1").id


def test_scoring_completion_notifies_the_submitter_on_pass(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_verdict(monkeypatch, ctx["item_id"], is_met=True)

    run_scan(client)

    notification = Notification.objects.get(
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED
    )
    assert notification.recipient_id == _participant_user_id()
    assert notification.context["class_id"] == ctx["class_id"]
    assert notification.context["problem_id"] == ctx["problem_id"]
    assert notification.context["submission_id"] == ctx["submission_id"]
    assert notification.context["attempt_number"] == 1
    assert notification.context["passed"] is True


def test_scoring_completion_notifies_the_submitter_on_fail(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_verdict(monkeypatch, ctx["item_id"], is_met=False)

    run_scan(client)

    notification = Notification.objects.get(
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED
    )
    assert notification.context["passed"] is False


def test_permanent_failure_finalization_also_notifies_the_submitter(client, db, monkeypatch):
    """자동 미달(`_finalize_platform_failure`)로 채점이 끝난 경우도 "채점이
    끝났다"이므로 침묵으로 남지 않는다(AC). 401·403(#355 이후 다른 갈래를
    타는 키 거부)이 아니라 잘린 응답으로 영구 실패를 흉내낸다."""

    ctx = _setup_submission(client)
    respond_with_permanent_failure(monkeypatch)

    run_scan(client)

    notification = Notification.objects.get(
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED
    )
    assert notification.recipient_id == _participant_user_id()
    assert notification.context["passed"] is False


def test_notification_is_never_sent_to_the_instructor(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_verdict(monkeypatch, ctx["item_id"], is_met=True)

    run_scan(client)

    assert not Notification.objects.filter(
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED,
        recipient_id=_instructor_user_id(),
    ).exists()


def test_notification_is_not_dispatched_to_any_channel(client, db, monkeypatch):
    """#301과 같은 규칙 — 문자로 나가지 않는다."""

    ctx = _setup_submission(client)
    respond_with_verdict(monkeypatch, ctx["item_id"], is_met=True)

    run_scan(client)

    notification = Notification.objects.get(
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED
    )
    assert notification.status == Notification.Status.NOT_DISPATCHED
    assert notification.dispatches.count() == 0


def test_joining_a_class_creates_no_notification(client, db):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    participant = login(client, uid="participant-1")

    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])

    assert not Notification.objects.filter(
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED
    ).exists()


def test_each_attempt_gets_its_own_notification(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_verdict(monkeypatch, ctx["item_id"], is_met=True)
    run_scan(client)

    second = submit_repository(
        client,
        ctx["participant"]["access"],
        ctx["class_id"],
        ctx["problem_id"],
        "https://github.com/octocat/hello-world-again",
    )
    respond_with_verdict(monkeypatch, ctx["item_id"], is_met=False)
    run_scan(client)

    notifications = Notification.objects.filter(
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED
    ).order_by("id")
    assert notifications.count() == 2
    by_submission = {n.context["submission_id"]: n for n in notifications}
    assert by_submission[ctx["submission_id"]].context["attempt_number"] == 1
    assert by_submission[second["id"]].context["attempt_number"] == 2
    assert by_submission[ctx["submission_id"]].context["passed"] is True
    assert by_submission[second["id"]].context["passed"] is False


def test_notification_creation_failure_does_not_prevent_scoring(client, db, monkeypatch):
    """AC: "알림 만들기가 실패해도 채점 자체는 그대로 끝난다." — 알림 쪽이
    죽어도(`create_notification`이 예외로 죽는 극단적인 경우) `ClassroomScore`는
    이미 커밋된 채로 남고, 스캔 결과도 정상 종결(`scored`)로 보고된다."""

    ctx = _setup_submission(client)
    respond_with_verdict(monkeypatch, ctx["item_id"], is_met=True)
    monkeypatch.setattr(
        "notifications.services.create_notification",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("notification backend is down")),
    )

    result = run_scan(client)

    assert result["count"] == 1
    assert result["rows"][0]["status"] == "scored"
    assert ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()
    assert not Notification.objects.filter(
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED
    ).exists()
