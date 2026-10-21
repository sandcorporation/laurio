"""채점이 한 번 돈 뒤에도 데모 시드를 다시 심을 수 있다 (#254, ADR-0064).

`seed_demo_contests` 는 「멱등하다 — 데모만 지우고 다시 만든다」고 적어 두었는데, 채점
스캔이 한 번 도는 순간 `Score.submission` 의 PROTECT 가 데모 Contest 삭제를 막아
그 약속이 깨졌다. append-only 우회(`hard_delete_e2e_fixture_rows`, #240)는 배포
환경에서 스스로 거부하므로 staging 에서는 재시드가 통째로 불가능했다.

이 파일이 고정하는 것 — 재시드는 **시드가 스스로 표지(`Contest.is_demo_seed`)를 붙인
행**만 지운다. 그래서 (1) 채점 뒤에도, staging 설정에서도 다시 심어지고, (2) 표지가 없는
행은 제목이 무엇이든 손대지 않으며, (3) production 은 여전히 거부하고, (4) #240 의
`hard_delete_e2e_fixture_rows` 는 그대로 배포 환경에서 거부한다(`test_ledger`).
"""

from __future__ import annotations

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from contests.models import Category, Contest, ContestSubmission, DeliverableType
from ledger.models import AppendOnlyError
from scoring.models import Score, hard_delete_demo_seed_scores
from storage.adapters.fake import FakeStorageAdapter
from submissions.scoring_basis import (
    NO_SCORING_INPUT_MODEL_VERSION,
    PLATFORM_FAILURE_MODEL_VERSION,
)
from tests.test_scoring import (
    CONTESTS_URL,
    _auth_header,
    _close_contest,
    _publish_contest,
    _run_pending,
    _source_object_key,
    _verified_user,
    _zip_bytes,
)

HOME_URL = "/api/contests/home"
_AUTO_ZERO_MODEL_VERSIONS = {NO_SCORING_INPUT_MODEL_VERSION, PLATFORM_FAILURE_MODEL_VERSION}


def _seed() -> None:
    call_command("seed_demo_contests", verbosity=0)


def _demo_scores():
    return Score.objects.filter(submission__contestsubmission__contest__is_demo_seed=True)


def _home_counts(client) -> dict[str, int]:
    return {g["bucket"]: len(g["contests"]) for g in client.get(HOME_URL).json()}


@pytest.fixture
def one_submission_per_scan(monkeypatch):
    """채점 스캔을 배치 1로 좁힌다 — 데모 제출 26건을 전부 채점하는 것은 이 파일이 묻는
    것(「재시드 뒤 채점이 다시 도달하는가」)과 무관하고 CPU 한도만 먹는다."""

    from dataclasses import replace

    from core import scans

    spec = scans.SCAN_REGISTRY["submission-scoring"]
    monkeypatch.setitem(scans.SCAN_REGISTRY, "submission-scoring", replace(spec, batch_size=1))


def _real_scored_submission(client) -> int:
    """정상 경로(개최 → 제출 → 마감 스캔 → 채점 스캔)로 만든 실데이터 Score 하나.

    시드가 아니라 **사람이 쓰는 API** 가 만든 행이라 `is_demo_seed` 표지가 없다 —
    재시드가 이 행을 어떤 경로로도 건드리지 않아야 한다.
    """

    category, _ = Category.objects.get_or_create(name="게임")
    landing_type, _ = DeliverableType.objects.get_or_create(
        name="웹 서비스", defaults={"minimum_prize": 500_000}
    )
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-254-1", "dev-ci-254-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])
    FakeStorageAdapter().write_object(source_key, _zip_bytes({"app.py": "MARKER\n"}))
    submit_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "assets": [{"kind": "source", "value": source_key}],
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [{"kind": "source_location", "value": "MARKER"}],
                }
            ],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert submit_resp.status_code == 201, submit_resp.content
    submission_id = submit_resp.json()["id"]
    _close_contest(client, contest, deadline=deadline)
    _run_pending(client)
    assert Score.objects.filter(submission_id=submission_id).exists()
    return submission_id


@pytest.mark.django_db
def test_reseed_after_scoring_replaces_demo_scores_and_grading_reaches_again(
    client, one_submission_per_scan
):
    """채점이 돈 뒤 다시 심으면 ProtectedError 없이 같은 한 벌이 다시 서고, 새 제출은
    채점 스캔에 다시 잡혀 **실제 판정**(자동 0% 두 종류가 아닌 것)을 받는다."""

    _seed()
    before = _home_counts(client)
    _run_pending(client)
    old_score_ids = set(_demo_scores().values_list("id", flat=True))
    assert old_score_ids, "데모의 마감된 공모전이 채점 스캔에 잡혀야 전제가 선다"

    _seed()

    assert _home_counts(client) == before
    assert not _demo_scores().exists()
    assert not Score.objects.filter(id__in=old_score_ids).exists()

    _run_pending(client)

    fresh = list(_demo_scores().values_list("model_version", flat=True))
    assert fresh, "재시드한 데모 제출이 채점 스캔에 다시 잡혀야 한다"
    assert not (set(fresh) & _AUTO_ZERO_MODEL_VERSIONS)


@pytest.mark.django_db
def test_reseed_works_in_the_staging_configuration_and_spares_real_scores(
    client, settings, one_submission_per_scan
):
    """staging 과 같은 설정(`IS_DEPLOYED_ENVIRONMENT`)에서도 재시드가 거부되지 않는다 —
    그리고 그 재시드는 **표지 없는 실데이터 Score** 를 지우지 않는다."""

    real_submission_id = _real_scored_submission(client)
    _seed()
    _run_pending(client)
    assert _demo_scores().exists()

    settings.CODEMIT_DEPLOYMENT_TARGET = "staging"
    settings.IS_DEPLOYED_ENVIRONMENT = True

    _seed()

    assert not _demo_scores().exists()
    assert Score.objects.filter(submission_id=real_submission_id).exists()
    assert Contest.objects.filter(is_demo_seed=True).count() == Contest.objects.filter(
        title__startswith="[데모] "
    ).count()


@pytest.mark.django_db
def test_production_still_refuses_both_the_seed_and_the_demo_score_purge(
    client, settings, one_submission_per_scan
):
    """production 은 시드도, 시드가 쓰는 Score 하드 삭제도 거부한다 — #240 의 방어가
    데모 표지로 좁혀졌을 뿐 production 에서는 한 줄도 느슨해지지 않았다."""

    _seed()
    _run_pending(client)
    count = _demo_scores().count()
    assert count

    settings.CODEMIT_DEPLOYMENT_TARGET = "production"
    settings.IS_DEPLOYED_ENVIRONMENT = True
    settings.IS_PRODUCTION_DEPLOYMENT = True

    with pytest.raises(CommandError, match="production"):
        call_command("seed_demo_contests", verbosity=0, stderr=StringIO())
    with pytest.raises(AppendOnlyError):
        hard_delete_demo_seed_scores()

    assert _demo_scores().count() == count


@pytest.mark.django_db
def test_demo_score_purge_cannot_be_widened_past_the_seed_marker(client):
    """`hard_delete_demo_seed_scores` 는 queryset 을 받지 않는다 — 호출부가 범위를 넓힐
    길이 없고, 표지 없는 Score 만 있으면 0건을 지운다."""

    real_submission_id = _real_scored_submission(client)

    assert hard_delete_demo_seed_scores() == 0
    assert Score.objects.filter(submission_id=real_submission_id).exists()


@pytest.mark.django_db
def test_migration_marks_only_what_the_old_seed_made(client):
    """표지가 생기기 전에 옛 시드가 심어 둔 한 벌(staging 에 실제로 있다)은 마이그레이션이
    옛 계약(접두어 + 시드 발주자 계정)으로 표지를 채운다 — 사람이 `[데모] ` 로 시작하는
    제목을 붙인 실제 공모전은 채우지 않는다."""

    import importlib

    from django.apps import apps

    mark = importlib.import_module(
        "contests.migrations.0010_contest_is_demo_seed"
    )._mark_rows_the_old_seed_made

    _seed()
    Contest.objects.filter(is_demo_seed=True).update(is_demo_seed=False)  # 표지 이전의 모양
    real_submission_id = _real_scored_submission(client)
    human_contest_id = ContestSubmission.objects.get(id=real_submission_id).contest_id
    Contest.objects.filter(id=human_contest_id).update(title="[데모] 사람이 붙인 제목")

    mark(apps=apps, schema_editor=None)

    assert Contest.objects.filter(is_demo_seed=False).count() == 1
    assert not Contest.objects.get(id=human_contest_id).is_demo_seed


def test_only_the_demo_seed_writes_the_marker(backend_sources):
    """`is_demo_seed=True` 를 쓰는 곳은 데모 시드 명령 하나뿐이다 — API·다른 시드가
    표지를 달기 시작하면 「표지 = 시드가 만든 행」이 거짓이 되고 그 위에 선 하드 삭제의
    근거가 사라진다. (`contest__is_demo_seed=True` 같은 **조회**는 쓰는 것이 아니다 —
    `scoring.models.hard_delete_demo_seed_scores` 가 그렇게 범위를 고정한다.)"""

    import re

    pattern = re.compile(r"(?<![\w.])is_demo_seed\s*=\s*True")
    writers = sorted(
        str(source.relative) for source in backend_sources if pattern.search(source.text)
    )
    assert writers == ["contests/management/commands/seed_demo_contests.py"]
