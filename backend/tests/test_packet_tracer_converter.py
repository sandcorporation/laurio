"""학생이 낸 `.pkt` 가 장비·결선·설정·주소 요약으로 채점자에게 간다 (#497, #495).

HTTP가 시임이다 — 강의실 소스 제출을 실제로 내고 채점 스캔을 돌려 벤더로 나간
프롬프트를 본다. 표본은 **직접 만든다**: 손으로 쓴 작은 XML
(`tests/fixtures/packet_tracer_lab.xml` — 라우터 1·스위치 1·PC 2·결선 3)을 같은
파이프라인의 역방향(`encrypt_xml`)으로 암호화한다. 남의 학생 과제는 커밋하지 않는다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from django.test import override_settings

from core.source_converters.packet_tracer._unpacket.crypto import encrypt_xml
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

PACKET_TRACER = "core.source_converters.packet_tracer.PacketTracerConverter"
LAB_XML = (Path(__file__).parent / "fixtures" / "packet_tracer_lab.xml").read_bytes()
UNREADABLE_LINE = "열 수 없는 Packet Tracer 파일"

pytestmark = pytest.mark.usefixtures("_packet_tracer_on")


@pytest.fixture
def _packet_tracer_on():
    with force_real_scoring_adapter(), override_settings(SOURCE_CONVERTERS=[PACKET_TRACER]):
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

    # 스캔은 큐에 넣기만 하고(#582) 채점은 그 자리에서 eager 로 끝난다 — 프롬프트가 증거다.
    assert result["rows"][0]["status"] == "queued", result
    return captured[0]["messages"][1]["content"]


def _assert_lab_summary(prompt: str) -> None:
    # 라우터·스위치는 running-config 원문으로
    assert "[R1] Router (모델 2911)" in prompt
    assert "hostname R1" in prompt
    assert " ip address 192.168.10.1 255.255.255.0" in prompt
    assert "switchport access vlan 10" in prompt
    # PC 는 포트 주소·게이트웨이·DNS 로
    assert "[PC1] Pc (모델 PC-PT)" in prompt
    assert "FastEthernet0: 192.168.10.11/255.255.255.0" in prompt
    assert "기본 게이트웨이: 192.168.10.1" in prompt
    assert "DNS 서버: 8.8.8.8" in prompt
    assert "FastEthernet0: DHCP 로 받음" in prompt
    # 결선
    assert "R1 GigabitEthernet0/0 ↔ SW1 GigabitEthernet0/1 (스트레이트)" in prompt
    assert "PC1 FastEthernet0 ↔ SW1 FastEthernet0/1 (스트레이트)" in prompt
    assert "PC2 FastEthernet0 ↔ SW1 FastEthernet0/2 (스트레이트)" in prompt
    # 화면 배치·옵션은 싣지 않는다
    for trap in ("PLACEMENT_TRAP_MARKER", "PHYSICAL_WORKSPACE_TRAP_MARKER", "OPTIONS_TRAP_MARKER"):
        assert trap not in prompt


def test_a_pkt_inside_a_zip_reaches_the_model_as_a_summary(client, db, monkeypatch):
    prompt = _scored_prompt(
        client, monkeypatch, files={"lab/network.pkt": encrypt_xml(LAB_XML), "README.txt": "README_MARKER\n"}
    )

    _assert_lab_summary(prompt)
    assert "# lab/network.pkt/요약.txt" in prompt
    assert "README_MARKER" in prompt


def test_a_single_uploaded_pkt_reaches_the_model_as_a_summary(client, db, monkeypatch):
    prompt = _scored_prompt(client, monkeypatch, raw_bytes=encrypt_xml(LAB_XML))

    _assert_lab_summary(prompt)


@pytest.mark.parametrize(
    "broken",
    [
        b"\x00\x01garbage that is not a packet tracer file\xff" * 10,
        encrypt_xml(LAB_XML)[:-200],  # 잘린 파일 — 태그가 맞지 않는다
    ],
    ids=["garbage", "truncated"],
)
def test_a_broken_pkt_leaves_an_unreadable_line_and_scoring_still_finishes(client, db, monkeypatch, broken):
    prompt = _scored_prompt(client, monkeypatch, files={"lab.pkt": broken, "main.txt": "OTHER_FILE_MARKER\n"})

    assert "# lab.pkt" in prompt
    assert UNREADABLE_LINE in prompt
    assert "OTHER_FILE_MARKER" in prompt


def test_decompression_stops_at_the_cap_even_when_the_size_header_lies(client, db, monkeypatch):
    # 압축 머리가 「작다」고 속여도 실제 해제가 상한에서 멈춘다.
    monkeypatch.setattr("core.source_converters.packet_tracer.MAX_XML_BYTES", 10_000)
    bomb = encrypt_xml(b"<PACKETTRACER5>" + b" " * 2_000_000 + b"</PACKETTRACER5>", declared_size=100)

    prompt = _scored_prompt(client, monkeypatch, files={"bomb.pkt": bomb})

    assert UNREADABLE_LINE in prompt


def test_xml_with_entity_declarations_is_not_parsed(client, db, monkeypatch):
    laughs = (
        b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
        b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
        b"<PACKETTRACER5><VERSION>&lol2;</VERSION></PACKETTRACER5>"
    )

    prompt = _scored_prompt(client, monkeypatch, files={"lolz.pkt": encrypt_xml(laughs)})

    assert UNREADABLE_LINE in prompt
    assert "lollollol" not in prompt
