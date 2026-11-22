"""같은 문제·같은 모델·같은 프롬프트면 이전 점수를 벤더 없이 다시 쓴다(#1287, 스펙 #1282) — 가짜 벤더(돈 0)."""

from __future__ import annotations

import pytest
from django.db.models import Q

from classroom import score_reuse
from classroom.api import _serialize_score as _serialize_current
from classroom.current_score import current_of


def _serialize_score(score, **kwargs):
    return _serialize_current(current_of(score), **kwargs)
from classroom.models import ChecklistItem, ClassroomScore, ClassroomSubmission, Problem
from classroom.scoring import FakeClassroomScoringAdapter
from submissions.scoring_basis import PLATFORM_FAILURE_MODEL_VERSION
from tests.classroom_scenarios import CLASSES_URL, auth_header, mine, create_class, create_open_problem, join_class, login, submit_repository


@pytest.fixture
def vendor_calls(monkeypatch):
    """가짜 벤더 호출 수를 센다. 돌려주는 `model_version` 은 문제의 모델 — 실제 벤더가 요청한 모델 이름을 돌려준다."""

    calls: list[int] = []
    original = FakeClassroomScoringAdapter.score

    def counting(self, scoring_input):
        calls.append(scoring_input.submission_id)
        return original(self, scoring_input)

    monkeypatch.setattr(FakeClassroomScoringAdapter, "score", counting)
    return calls


@pytest.fixture
def class_with_problem(client, db, monkeypatch):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, required_labels=["README 가 있다"])
    model = Problem.objects.get(pk=problem.id).effective_model()
    monkeypatch.setattr(FakeClassroomScoringAdapter, "model_version", model)
    return {"instructor": instructor, "class_id": class_id, "problem": problem}


@pytest.fixture
def submit(client, django_capture_on_commit_callbacks):
    """새 학생으로 가입해 낸다 — 제출의 `on_commit` 즉시 채점이 시험 트랜잭션 안에서도 돈다."""

    def run(ctx, uid: str) -> ClassroomScore:
        participant = login(client, uid=uid)
        join_class(client, participant["access"], ctx["class_id"], instructor_access=ctx["instructor"]["access"])
        with django_capture_on_commit_callbacks(execute=True):
            submission_id = submit_repository(client, participant["access"], ctx["class_id"], ctx["problem"].id)["id"]
        return ClassroomScore.objects.get(submission_id=submission_id)

    return run


def test_off_by_default_every_attempt_calls_the_vendor(client, class_with_problem, submit, vendor_calls, monkeypatch):
    monkeypatch.delenv("CLASSROOM_SCORE_REUSE", raising=False)
    first = submit(class_with_problem, "p-1")
    second = submit(class_with_problem, "p-2")

    assert len(vendor_calls) == 2
    assert not score_reuse.score_reused(first) and not score_reuse.score_reused(second)


def test_on_the_same_input_a_second_attempt_does_not_call_the_vendor(
    client, class_with_problem, submit, vendor_calls, monkeypatch
):
    monkeypatch.setenv("CLASSROOM_SCORE_REUSE", "on")
    first = submit(class_with_problem, "p-1")
    second = submit(class_with_problem, "p-2")  # 다른 학생 — 같은 문제 안이면 재사용한다

    assert len(vendor_calls) == 1
    assert second.model_version == first.model_version
    assert second.prompt == first.prompt
    assert [(r["checklist_item_id"], r["is_met"], r["verdict"], r["reasoning"]) for r in second.reasoning] == [
        (r["checklist_item_id"], r["is_met"], r["verdict"], r["reasoning"]) for r in first.reasoning
    ]
    assert all(r[score_reuse.REUSED_KEY] == first.id for r in second.reasoning)
    # 강사 응답은 재사용을 알리고, 학생 응답에는 원본에 대한 어떤 것도 없다.
    assert _serialize_score(second).reused is True
    assert _serialize_score(first).reused is False
    participant_view = _serialize_score(second, hidden_items={}).model_dump_json()
    assert score_reuse.REUSED_KEY not in participant_view
    assert _serialize_score(second, hidden_items={}).reused is False


def test_a_changed_checklist_calls_the_vendor_again(client, class_with_problem, submit, vendor_calls, monkeypatch):
    monkeypatch.setenv("CLASSROOM_SCORE_REUSE", "on")
    submit(class_with_problem, "p-1")
    ChecklistItem.objects.filter(pk=class_with_problem["problem"].item_id).update(label="테스트가 있다")
    submit(class_with_problem, "p-2")

    assert len(vendor_calls) == 2


def test_a_different_model_calls_the_vendor_again(client, class_with_problem, submit, vendor_calls, monkeypatch):
    monkeypatch.setenv("CLASSROOM_SCORE_REUSE", "on")
    submit(class_with_problem, "p-1")
    Problem.objects.filter(pk=class_with_problem["problem"].id).update(model="gpt-5.4-nano")
    monkeypatch.setattr(FakeClassroomScoringAdapter, "model_version", "gpt-5.4-nano")
    submit(class_with_problem, "p-2")

    assert len(vendor_calls) == 2


def test_platform_failure_scores_and_other_problems_are_never_reused(client, class_with_problem, submit, monkeypatch):
    monkeypatch.setenv("CLASSROOM_SCORE_REUSE", "on")
    first = submit(class_with_problem, "p-1")
    problem = first.submission.problem
    model = problem.effective_model()
    same_prompt = Q(prompt=first.prompt)

    assert score_reuse.find_reusable_score(
        problem, model=model, input_filter=same_prompt, exclude_submission_id=0
    ) == first
    # 플랫폼 자동 점수는 뺀다.
    ClassroomScore.objects.filter(pk=first.pk).update(model_version=PLATFORM_FAILURE_MODEL_VERSION)
    assert (
        score_reuse.find_reusable_score(problem, model=model, input_filter=same_prompt, exclude_submission_id=0)
        is None
    )
    # 다른 문제는 안 쓴다.
    ClassroomScore.objects.filter(pk=first.pk).update(model_version=model)
    other = Problem.objects.exclude(pk=problem.pk).first() or Problem.objects.create(
        classroom=problem.classroom, title="다른 문제"
    )
    assert score_reuse.find_by_prompt(other, model=model, prompt=first.prompt, exclude_submission_id=0) is None


def test_model_name_pattern_accepts_a_dated_variant_but_not_a_longer_name():
    import re

    pattern = re.compile(score_reuse.model_version_pattern("gpt-5"))
    assert pattern.match("gpt-5") and pattern.match("gpt-5-2025-08-07")
    assert not pattern.match("gpt-5-mini") and not pattern.match("gpt-5-mini-2025-08-07")


def test_an_attempt_never_reuses_its_own_score(client, class_with_problem, submit, vendor_calls, monkeypatch):
    monkeypatch.setenv("CLASSROOM_SCORE_REUSE", "on")
    first = submit(class_with_problem, "p-1")
    assert (
        score_reuse.find_by_prompt(
            first.submission.problem,
            model=first.submission.problem.effective_model(),
            prompt=first.prompt,
            exclude_submission_id=first.submission_id,
        )
        is None
    )
    assert ClassroomSubmission.objects.count() == 1


def test_over_http_the_instructor_list_marks_reuse_and_the_students_own_view_does_not(
    client, class_with_problem, submit, monkeypatch
):
    monkeypatch.setenv("CLASSROOM_SCORE_REUSE", "on")
    ctx = class_with_problem
    submit(ctx, "p-1")
    second = submit(ctx, "p-2")
    problem_id, class_id = ctx["problem"].id, ctx["class_id"]

    listed = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions", **auth_header(ctx["instructor"]["access"])
    ).json()
    assert sorted(row["score"]["reused"] for row in listed) == [False, True]

    student = login(client, uid="p-2")
    own = mine(client, student["access"], class_id, problem_id)["submissions"][0]["score"]
    assert own["reused"] is False
    assert score_reuse.REUSED_KEY not in str(own) and second.reasoning[0][score_reuse.REUSED_KEY] is not None
