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


def _scored_submission(client) -> int:
    instructor = login(client, uid="instructor-1262", email=EMAIL)
    class_id = create_class(client, instructor["access"], name=CLASS_NAME)
    problem = create_open_problem(
        client, instructor["access"], class_id, title="두 수 더하기", submission_formats=["source"],
        required_labels=["add_two_numbers"], optional_labels=["곱하기 함수"],
    )
    student = login(client, uid="student-1262")
    join_class(client, student["access"], class_id, instructor_access=instructor["access"], display_name=STUDENT)
    submitted = submit_source(
        client, student["access"], class_id, problem.id, participant_user_id=user_id("student-1262"),
        files={"main.py": SOURCE},
    )
    run_scan(client)
    return submitted["id"]


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


def test_help_says_to_delete_the_server_copy_after_moving_it():
    assert "운영 서버에 남은 export 파일은 work 로 옮긴 뒤 지운다(대장)." in Command.help
