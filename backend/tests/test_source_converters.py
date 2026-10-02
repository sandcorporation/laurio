"""소스 선별이 읽을 수 없는 파일을 등록된 변환 플러그인에게 넘긴다 (#496, #495).

HTTP가 시임이다 — 강의실 소스 제출을 실제로 내고 채점 스캔을 돌려, 벤더로 나간
프롬프트에 무엇이 실렸는지 본다(`test_classroom_scoring.py`의 `captured_prompts`
관용구). 플러그인은 테스트 전용(`tests.source_converter_doubles`)이다 — 실제
형식 플러그인(Packet Tracer)은 #497 이 덮는다.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.test import override_settings

from tests.classroom_scenarios import (
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    join_class,
    login,
    respond_with_verdict,
    run_scan,
    submit_source,
    user_id,
)
from tests.source_converter_doubles import FAKEBAD_MAGIC, fakebin

MARKER = "tests.source_converter_doubles.MarkerConverter"
EXPLODING = "tests.source_converter_doubles.ExplodingConverter"


@pytest.fixture(autouse=True)
def _force_real_scoring_adapter():
    with force_real_scoring_adapter():
        yield


def _scored_prompt(client, monkeypatch, *, files=None, raw_bytes=b"") -> str:
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
        files=files,
        raw_bytes=raw_bytes,
    )
    captured: list = []
    respond_with_verdict(monkeypatch, problem.item_id, is_met=True, capture=captured)

    result = run_scan(client)

    assert result["rows"][0]["status"] == "scored", result
    return captured[0]["messages"][1]["content"]


@override_settings(SOURCE_CONVERTERS=[MARKER])
def test_a_binary_file_inside_a_zip_reaches_the_model_as_converted_text(client, db, monkeypatch):
    prompt = _scored_prompt(
        client,
        monkeypatch,
        files={"lab/topology.bin": fakebin("ROUTER_CONFIG_MARKER"), "main.py": "PLAIN_MARKER\n"},
    )

    assert "ROUTER_CONFIG_MARKER" in prompt
    assert "lab/topology.bin" in prompt
    assert "PLAIN_MARKER" in prompt


@override_settings(SOURCE_CONVERTERS=[MARKER])
def test_a_single_uploaded_binary_file_is_converted_by_content_not_by_name(client, db, monkeypatch):
    # 단일 파일 업로드는 선별 안에서 이름이 `source` 다 — 판정은 내용으로 한다.
    prompt = _scored_prompt(client, monkeypatch, raw_bytes=fakebin("SINGLE_FILE_MARKER"))

    assert "SINGLE_FILE_MARKER" in prompt


@override_settings(SOURCE_CONVERTERS=[EXPLODING, MARKER])
def test_a_converter_that_raises_does_not_stop_the_other_files(client, db, monkeypatch):
    prompt = _scored_prompt(
        client,
        monkeypatch,
        files={"a.bin": fakebin("CONVERTED_AFTER_EXPLOSION_MARKER"), "main.py": "PLAIN_MARKER\n"},
    )

    assert "PLAIN_MARKER" in prompt
    assert "CONVERTED_AFTER_EXPLOSION_MARKER" in prompt


@override_settings(SOURCE_CONVERTERS=[MARKER])
def test_a_file_whose_format_was_confirmed_but_failed_to_convert_leaves_a_line(client, db, monkeypatch):
    prompt = _scored_prompt(
        client,
        monkeypatch,
        files={"broken.bin": FAKEBAD_MAGIC + b"\x01\x02", "main.py": "PLAIN_MARKER\n"},
    )

    assert "# broken.bin" in prompt
    assert "열 수 없는 가짜 바이너리 파일" in prompt
    assert "PLAIN_MARKER" in prompt


@override_settings(SOURCE_CONVERTERS=[MARKER])
def test_an_unrecognised_binary_is_still_dropped_silently(client, db, monkeypatch):
    prompt = _scored_prompt(
        client,
        monkeypatch,
        files={"notes.bin": b"\x00\x00UNKNOWN_BINARY_TRAP", "main.py": "PLAIN_MARKER\n"},
    )

    assert "UNKNOWN_BINARY_TRAP" not in prompt
    assert "notes.bin" not in prompt


@override_settings(SOURCE_CONVERTERS=[])
def test_with_no_converters_a_binary_file_is_dropped_as_before(client, db, monkeypatch):
    prompt = _scored_prompt(
        client,
        monkeypatch,
        files={"lab/topology.bin": fakebin("ROUTER_CONFIG_MARKER"), "main.py": "PLAIN_MARKER\n"},
    )

    assert "ROUTER_CONFIG_MARKER" not in prompt
    assert "PLAIN_MARKER" in prompt


@pytest.mark.parametrize(
    "path",
    ["tests.source_converter_doubles.DoesNotExist", "tests.source_converter_doubles.NotAConverter"],
)
def test_check_rejects_a_converter_path_that_cannot_be_used(path):
    with override_settings(SOURCE_CONVERTERS=[path]), pytest.raises(SystemCheckError):
        call_command("check")


def test_check_accepts_registered_converters():
    with override_settings(SOURCE_CONVERTERS=[MARKER, EXPLODING]):
        call_command("check")
