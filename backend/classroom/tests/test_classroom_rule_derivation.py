"""staged 규칙 자동 도출(#1293, 스펙 #1292) — 강사가 규칙을 넣지 않아도 채점이 항목 글에서 규칙을 도출해 둔다.

가짜 벤더만 쓴다(`core.llm_scoring.requests.post` 를 바꾼다). 도출 요청과 채점 요청은 프롬프트 첫 줄로 가른다.
"""

from __future__ import annotations

import json

import pytest

from classroom import rule_derivation
from classroom.models import ChecklistItem, Class, ClassroomScore
from classroom.tests.test_classroom_machine_check import TREE, _item_url, _world, staged  # noqa: F401  # 갈래 바꿔 끼우기(#1310)
from tests.classroom_scenarios import (
    CLASSES_URL,
    DERIVATION_PROMPT_HEAD,
    FakeVendorResponse,
    auth_header,
    create_class,
    derivation_body,
    derivation_item_ids,
    force_real_scoring_adapter,
    is_derivation_request,
    join_class,
    login,
    mine,
    openai_verdicts_body,
    run_scan,
    submit_source,
    user_id,
)

pytestmark = pytest.mark.usefixtures("reset_rate_limits")

APP_EXISTS = {"kind": "static", "rule": {"kind": "path_exists", "path": "**/src/app.py"}}
RUNS = {"kind": "run", "rule": None}




class Vendor:
    """도출·채점 요청을 가려 쌓고, 도출에는 `answers`(항목 글 → 답)로, 채점에는 물은 항목 모두 충족으로 답한다."""

    def __init__(self, monkeypatch, answers: dict[str, dict] | None = None, *, derivation_tokens: int = 0) -> None:
        self.answers = answers or {}
        self.derivation_tokens = derivation_tokens
        self.fail_derivation = False
        self.derivations: list[list[int]] = []
        self.scorings: list[list[int]] = []
        self.labels: dict[int, str] = {}
        monkeypatch.setattr("core.llm_scoring.requests.post", self._handler)

    def _handler(self, *args, **kwargs):
        payload = kwargs["json"]
        if is_derivation_request(payload):
            ids = derivation_item_ids(payload)
            self.derivations.append(ids)
            if self.fail_derivation:
                return FakeVendorResponse(500, {"error": {"message": "boom"}})
            by_id = {i: self.answers[self.labels[i]] for i in ids if self.labels.get(i) in self.answers}
            return FakeVendorResponse(200, derivation_body(payload, by_id, total_tokens=self.derivation_tokens))
        ids = [int(k) for k in payload["response_format"]["json_schema"]["schema"]["properties"]["verdicts"]["properties"]]
        self.scorings.append(ids)
        return FakeVendorResponse(
            200,
            openai_verdicts_body(
                [{"requirement_id": i, "verdict": "met", "reasoning": "충족", "citations": []} for i in ids]
            ),
        )


def _world_with(client, vendor: Vendor, items: list[tuple[str, dict | None]]) -> dict:
    ctx = _world(client, items)
    vendor.labels = {item_id: label for item_id, (label, _) in zip(ctx["item_ids"], items)}
    return ctx


def _submit_as(client, ctx: dict, uid: str) -> None:
    participant = login(client, uid=uid)
    join_class(client, participant["access"], ctx["class_id"], instructor_access=ctx["access"])
    submit_source(
        client, participant["access"], ctx["class_id"], ctx["problem_id"], participant_user_id=user_id(uid), files=TREE
    )


def test_the_prompt_head_matches_the_test_vendor():
    assert rule_derivation.PROMPT_HEAD == DERIVATION_PROMPT_HEAD


def test_rules_are_derived_once_per_text_and_again_after_an_edit(client, db, monkeypatch, staged):
    with force_real_scoring_adapter():
        vendor = Vendor(monkeypatch, {"앱 진입 파일이 있다": APP_EXISTS, "시험이 통과한다": RUNS})
        ctx = _world_with(
            client,
            vendor,
            [("앱 진입 파일이 있다", None), ("시험이 통과한다", None), ("코드가 읽기 쉽다", None)],
        )
        app, runs, judged = ctx["item_ids"]
        run_scan(client)

        assert vendor.derivations == [[app, runs, judged]]
        # 도출 규칙이 충족인 항목은 모델에 묻지 않는다. 「실행 필요」는 판단과 같이 모델에게 간다.
        assert vendor.scorings == [[runs, judged]]
        score = ClassroomScore.objects.get()
        assert [(r["checklist_item_id"], r["source"]) for r in score.reasoning] == [
            (app, "machine"),
            (runs, "model"),
            (judged, "model"),
        ]
        stored = {i.id: (i.derived_kind, i.derived_rule) for i in ChecklistItem.objects.all()}
        assert stored == {
            app: ("static", {"kind": "path_exists", "path": "**/src/app.py"}),
            runs: ("run", None),
            judged: ("judge", None),
        }

        # 같은 글이면 두 번째 채점은 도출을 부르지 않는다.
        _submit_as(client, ctx, "participant-2")
        run_scan(client)
        assert len(vendor.derivations) == 1

        # 글을 고친 항목만 다시 도출한다.
        edited = client.patch(
            _item_url(ctx["class_id"], ctx["problem_id"], judged),
            data={"label": "함수 이름이 뜻을 드러낸다"},
            content_type="application/json",
            **auth_header(ctx["access"]),
        )
        assert edited.status_code == 200, edited.content
        vendor.labels[judged] = "함수 이름이 뜻을 드러낸다"
        _submit_as(client, ctx, "participant-3")
        run_scan(client)
        assert vendor.derivations[1:] == [[judged]]


def test_a_malformed_rule_becomes_judge(client, db, monkeypatch, staged):
    with force_real_scoring_adapter():
        broken = {"kind": "static", "rule": {"kind": "file_contains", "path": "src/*.py"}}  # text·pattern 둘 다 없음
        vendor = Vendor(monkeypatch, {"main 이 있다": broken, "엉뚱한 꼴": {"kind": "static", "rule": {"kind": "exec"}}})
        ctx = _world_with(client, vendor, [("main 이 있다", None), ("엉뚱한 꼴", None)])
        run_scan(client)

    assert {i.derived_kind for i in ChecklistItem.objects.all()} == {"judge"}
    assert vendor.scorings == [ctx["item_ids"]]


def test_a_failed_derivation_does_not_block_scoring(client, db, monkeypatch, staged):
    with force_real_scoring_adapter():
        vendor = Vendor(monkeypatch, {"앱 진입 파일이 있다": APP_EXISTS})
        vendor.fail_derivation = True
        ctx = _world_with(client, vendor, [("앱 진입 파일이 있다", None)])
        run_scan(client)

    assert ClassroomScore.objects.get().reasoning[0]["source"] == "model"
    assert vendor.scorings == [ctx["item_ids"]]
    # 저장하지 않았으니 다음 채점이 다시 묻는다.
    assert ChecklistItem.objects.get().derived_text_hash == ""


def test_items_with_an_instructor_rule_are_not_derived(client, db, monkeypatch, staged):
    with force_real_scoring_adapter():
        vendor = Vendor(monkeypatch, {})
        ctx = _world_with(
            client,
            vendor,
            [("src/app.py 가 있다", {"kind": "path_exists", "path": "src/app.py"}), ("코드가 읽기 쉽다", None)],
        )
        run_scan(client)

    assert vendor.derivations == [[ctx["item_ids"][1]]]


def test_single_call_never_derives(client, db, monkeypatch):
    with force_real_scoring_adapter():
        vendor = Vendor(monkeypatch, {"앱 진입 파일이 있다": APP_EXISTS})
        _world_with(client, vendor, [("앱 진입 파일이 있다", None)])
        run_scan(client)

    assert vendor.derivations == []
    assert len(vendor.scorings) == 1
    assert ChecklistItem.objects.get().derived_kind == ""


def test_derivation_tokens_count_toward_the_class_usage(client, db, monkeypatch, staged):
    with force_real_scoring_adapter():
        vendor = Vendor(monkeypatch, {"앱 진입 파일이 있다": APP_EXISTS}, derivation_tokens=123)
        _world_with(client, vendor, [("앱 진입 파일이 있다", None)])
        run_scan(client)

    # 모든 항목이 기계 충족이라 채점 호출은 없고, 도출 호출의 토큰만 더해진다.
    assert vendor.scorings == []
    assert Class.objects.get().token_usage_total == 123


def test_the_derivation_is_shown_to_the_instructor_only(client, db, monkeypatch, staged):
    with force_real_scoring_adapter():
        vendor = Vendor(monkeypatch, {"앱 진입 파일이 있다": APP_EXISTS})
        ctx = _world_with(client, vendor, [("앱 진입 파일이 있다", None)])
        run_scan(client)

    url = f"{CLASSES_URL}/{ctx['class_id']}/problems/{ctx['problem_id']}"
    instructor_item = client.get(url, **auth_header(ctx["access"])).json()["checklist_items"][0]
    assert instructor_item["derived_kind"] == "static"
    assert instructor_item["derived_rule"] == APP_EXISTS["rule"]
    shown = mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    participant_item = shown["problem"]["checklist_items"][0]
    assert participant_item.get("derived_kind") is None
    assert participant_item.get("derived_rule") is None
    assert json.dumps(participant_item).find("app.py") == -1


def _rule_fields(problem_id: int) -> dict[str, tuple]:
    return {
        i.label: (i.machine_rule, i.derived_rule, i.derived_kind, i.derived_text_hash, i.derived_model)
        for i in ChecklistItem.objects.filter(problem_id=problem_id)
    }


def _post(client, url: str, access: str, data: dict) -> dict:
    response = client.post(url, data=data, content_type="application/json", **auth_header(access))
    assert response.status_code == 201, response.content
    return response.json()


def test_templates_carry_the_rule_fields_and_skip_derivation_for_the_same_text(client, db, monkeypatch, staged):
    """받아들임(#1296) — 규칙·도출 칸이 있는 문제를 템플릿으로 내보내고 다시 가져오면 칸이 남고, 같은 글이면 도출 호출이 없다."""

    with force_real_scoring_adapter():
        vendor = Vendor(monkeypatch, {"앱 진입 파일이 있다": APP_EXISTS})
        ctx = _world_with(
            client,
            vendor,
            [
                ("앱 진입 파일이 있다", None),
                ("코드가 읽기 쉽다", None),
                ("시험 폴더가 있다", {"kind": "path_exists", "path": "tests/*.py"}),
            ],
        )
        run_scan(client)
        assert len(vendor.derivations) == 1
        source = _rule_fields(ctx["problem_id"])
        assert source["시험 폴더가 있다"][0] and source["앱 진입 파일이 있다"][2] == "static"
        access, class_id = ctx["access"], ctx["class_id"]

        # 문제 템플릿: 내보내기 → 다른 클래스로 가져오기.
        share = _post(
            client,
            f"{CLASSES_URL}/{class_id}/problems/{ctx['problem_id']}/publish-template",
            access,
            {"publisher_display_name": "김강사"},
        )["share_code"]
        target = create_class(client, access)
        problem_id = _post(client, f"/api/classroom/problem-templates/{share}/import", access, {"target_class_id": target})["id"]
        assert _rule_fields(problem_id) == source

        # 클래스 템플릿: 내보내기 → 새 클래스로 가져오기.
        class_share = _post(client, f"{CLASSES_URL}/{class_id}/publish-template", access, {"publisher_display_name": "김강사"})[
            "share_code"
        ]
        new_class = _post(client, f"/api/classroom/class-templates/{class_share}/import", access, {"name": "가져온 클래스"})["id"]
        (imported,) = set(ChecklistItem.objects.filter(problem__classroom_id=new_class).values_list("problem_id", flat=True))
        assert _rule_fields(imported) == source

        # 가져온 문제를 채점해도 같은 글이라 도출을 다시 부르지 않는다.
        opened = client.post(f"{CLASSES_URL}/{target}/problems/{problem_id}/open", content_type="application/json", **auth_header(access))
        assert opened.status_code == 200, opened.content
        _submit_as(client, {**ctx, "class_id": target, "problem_id": problem_id}, "participant-2")
        run_scan(client)
        assert len(vendor.derivations) == 1
        assert len(vendor.scorings) == 2
