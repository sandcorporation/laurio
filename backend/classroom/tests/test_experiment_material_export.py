"""#1262: 채점 방식 실험의 재료 사본을 강의실에서 꺼낸다(`export_experiment_material`) — 읽기만 하고, 개인 필드가 없다.

고정 예시는 지어낸 소스다. 제출은 HTTP 시나리오로 만들고 흉내 어댑터로 채점한다.
"""

from __future__ import annotations

import io
import json
import stat
import tarfile

import pytest
from django.core.management import CommandError, call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext

from classroom.management.commands.export_experiment_material import Command
from core import experiment_material as em
from tests.classroom_scenarios import (
    create_class,
    create_open_problem,
    join_class,
    login,
    run_scan,
    submit_source,
    user_id,
)

STUDENT = "김지어낸학생"
CLASS_NAME = "지어낸반-1262"
EMAIL = "made-up-instructor-1262@example.com"
SOURCE = "def add_two_numbers(a, b):\n    return a + b\n"


def _scored_submissions(client, count: int = 1) -> list[int]:
    instructor = login(client, uid="instructor-1262", email=EMAIL)
    class_id = create_class(client, instructor["access"], name=CLASS_NAME)
    problem = create_open_problem(
        client, instructor["access"], class_id, title="두 수 더하기", submission_formats=["source"],
        required_labels=["add_two_numbers"], optional_labels=["곱하기 함수"],
    )
    ids = []
    for n in range(count):
        uid = f"student-1262-{n}"
        student = login(client, uid=uid)
        join_class(client, student["access"], class_id, instructor_access=instructor["access"], display_name=f"{STUDENT}{n}")
        submitted = submit_source(
            client, student["access"], class_id, problem.id, participant_user_id=user_id(uid), files={"main.py": SOURCE},
        )
        ids.append(submitted["id"])
    run_scan(client)
    return ids


def _scored_submission(client) -> int:
    return _scored_submissions(client)[0]


def _export(*args: str) -> str:
    out = io.StringIO()
    call_command("export_experiment_material", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_export_reads_only_writes_0600_and_prints_only_count_and_size(client, tmp_path):
    sid = _scored_submission(client)
    out_path = tmp_path / "m.tar.gz"

    with CaptureQueriesContext(connection) as queries:
        printed = _export("--classroom-submissions", str(sid), "--name", "t1262", "--out", str(out_path))

    writes = [q["sql"] for q in queries if not q["sql"].lstrip().upper().startswith("SELECT")]
    assert writes == []
    assert stat.S_IMODE(out_path.stat().st_mode) == 0o600
    assert printed == f"1건 · {out_path.stat().st_size} 바이트\n"
    assert SOURCE not in printed and em.pseudonym("t1262", sid) not in printed


@pytest.mark.django_db
def test_export_holds_no_personal_fields_and_only_a_pseudonym(client, tmp_path, monkeypatch):
    monkeypatch.setattr(em, "TEMP_ROOTS", ())  # 시험 임시 폴더는 /tmp 아래일 수 있다(자리 규칙은 개발 환경 쪽 시험이 본다)
    sid = _scored_submission(client)
    out_path = tmp_path / "m.tar.gz"
    _export("--classroom-submissions", str(sid), "--name", "t1262", "--out", str(out_path))

    with tarfile.open(out_path, "r:gz") as tar:
        blobs = {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}  # type: ignore[union-attr]  # 파일만
    everything = b"".join(blobs.values()).decode("utf-8", "replace")
    for personal in (STUDENT, CLASS_NAME, EMAIL, "student-1262", "instructor-1262"):
        assert personal not in everything
    pid = em.pseudonym("t1262", sid)
    assert set(blobs) == {"manifest.json", f"items/{pid}.json", f"items/{pid}.src"}
    item = json.loads(blobs[f"items/{pid}.json"])
    assert set(item) == {"material_id", "asset_kind", "problem", "checklist", "verdicts", "model_version"}
    assert set(json.loads(blobs["manifest.json"])) == {"format", "name", "exported_at", "count", "checksum"}
    loaded = em.load(out_path, repo_root=tmp_path / "elsewhere")
    assert [i.material_id for i in loaded.items] == [pid]
    assert {c.label: c.grade for c in loaded.items[0].checklist} == {"add_two_numbers": "required", "곱하기 함수": "optional"}
    assert loaded.items[0].production_score() == 100.0  # 흉내 채점: 필수 문구가 소스에 있다


@pytest.mark.django_db
def test_export_refuses_an_unscored_submission_and_writes_nothing(client, tmp_path):
    out_path = tmp_path / "m.tar.gz"
    with pytest.raises(CommandError, match="강의실 제출이 없다: 999999"):
        _export("--classroom-submissions", "999999", "--name", "t", "--out", str(out_path))
    assert not out_path.exists()


def _unextractable(monkeypatch, reasons: dict[int, Exception]) -> None:
    """제출별로 소스를 꺼낼 수 없게 한다 — 운영의 「고정 커밋 없음」「저장소 404」 꼴."""
    from classroom import experiment_material as cm

    real = cm._source_bytes

    def fake(asset):
        exc = reasons.get(asset.submission_id)
        if exc is not None:
            raise exc
        return real(asset)

    monkeypatch.setattr(cm, "_source_bytes", fake)


@pytest.mark.django_db
def test_export_skips_unextractable_submissions_and_prints_the_skipped_line(client, tmp_path, monkeypatch):
    from classroom import experiment_material as cm

    a, b, c = _scored_submissions(client, 3)
    _unextractable(monkeypatch, {
        b: em.MaterialError("저장소 제출에 고정 커밋이 없다 — 운영이 본 내용을 다시 받을 수 없다"),
        c: cm.RepositoryUnreachable(),
    })
    out_path = tmp_path / "m.tar.gz"

    printed = _export("--classroom-submissions", f"{a},{b},{c}", "--name", "t1267", "--out", str(out_path))

    assert printed.splitlines() == [
        f"1건 · {out_path.stat().st_size} 바이트",
        f"건너뜀 2건 — 고정 커밋 없음 1({b}), 저장소 닿지 않음 1({c})",
    ]
    assert SOURCE not in printed and "github" not in printed.lower()
    with tarfile.open(out_path) as tar:
        manifest = json.loads(tar.extractfile("manifest.json").read())
    assert manifest["count"] == 1


@pytest.mark.django_db
def test_export_fails_and_writes_nothing_when_every_submission_is_skipped(client, tmp_path, monkeypatch):
    (a,) = _scored_submissions(client)
    _unextractable(monkeypatch, {a: em.MaterialError("저장소 제출에 고정 커밋이 없다 — x")})
    out_path = tmp_path / "m.tar.gz"
    with pytest.raises(CommandError, match="꺼낼 수 있는 제출이 없다 — 건너뜀 1건 — 고정 커밋 없음 1"):
        _export("--classroom-submissions", str(a), "--name", "t", "--out", str(out_path))
    assert not out_path.exists()


def test_help_says_to_delete_the_server_copy_after_moving_it():
    assert "운영 서버에 남은 export 파일은 work 로 옮긴 뒤 지운다(대장)." in Command.help
