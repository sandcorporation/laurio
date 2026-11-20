"""앱 사이 결합이 선언 표(`backend/app_deps.toml`) 안에 있고, 그 표가 한 방향 층이다 — #1086(처음은 #269, ADR-0037).

**ADR-0037 이 Classroom 을 별도 서비스로 가르지 않기로 하면서 진 빚이 이것이다.** 프로세스가 갈려 있으면 잘못된
import 는 애초에 컴파일되지 않는다. 한 프로세스 안에서는 `from contests.models import Contest` 한 줄이 그냥 돌아가고,
함수 안 지연 import·`"contests.Contest"` 문자열·시그널 연결·설정의 dotted path 는 리뷰에서 가장 안 읽힌다. 그래서
기계가 매 커밋 확인한다.

## 표가 말하는 것

앱마다 `group`(shared·contest·classroom)과 두 칸 — `uses`(부르는 아래 앱), `plugs`(제 구현을 올리는 아래 앱 —
등록 자리·시그널·설정 dotted path). 아래 앱이 Django 역관계로 위 앱의 행을 걷는 ORM 경로는 받을 칸이 없다(#1102). 세는 법은
`scripts/app_deps.py` 머리말이 들고 있다. 이 시험은 그 분석기에 ORM 경로(모델 관계가 있어야 걷는다)를 더해 맞댄다.

- 코드의 결합이 표에 없으면 빨강, 표의 선언이 코드에 없으면 빨강(선언은 좁게 — 선택 실행 #1088 이 이 표만 읽는다).
- `uses`·`plugs` 가 순환이면 빨강.
- 공유층은 기능 앱에 묶이지 않는다. 강의실 ↮ 공모전 가족(ADR-0037) — 어느 칸으로도.
- `APP-BOUNDARY-EXCEPTION` 표식은 받지 않는다. 문이 있으면 마감에 몰린 사람이 그 문을 쓴다 — 결합은 표에 적거나
  `core.registry` 자리로 뒤집는다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from django.conf import settings

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "app_deps.py"


def _load():
    spec = importlib.util.spec_from_file_location("app_deps", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


deps = _load()
D = deps.Declared

#: 두 제품이 나눠 쓰는 층 — 다른 구조 시험(`test_runtime_settings_port`)이 이 이름으로 읽는다
SHARED = frozenset(app for app, d in deps.load_table().items() if d.group == "shared")


@pytest.fixture(scope="module")
def repository():
    """저장소 전체를 한 번 읽고 센다 — 모듈 픽스처라 시험 하나의 CPU 한도 밖이다."""

    table = deps.load_table()
    sources = deps.app_sources()
    raw, marked = deps.repository_couplings(sources)
    found = deps.classify(raw, table) + deps.orm_couplings(sources, table, deps.django_resolver())
    return table, found, marked


# --- 저장소 전체 -----------------------------------------------------------------


def test_the_declared_table_matches_the_code(repository):
    """실패 문구가 어느 파일 어느 줄인지와 무엇을 할지를 말한다 — 규칙만 있고 길이 없으면 다음 사람이 규칙을 지운다."""

    table, found, marked = repository
    installed = {app for app in settings.INSTALLED_APPS if not app.startswith("django.")}
    problems = deps.problems(table, found, marked, installed)
    assert not problems, "앱 의존 선언과 코드가 어긋난다:\n" + "\n".join(problems)


def test_the_script_reads_installed_apps_like_django():
    """선택 실행은 Django 없이 표만 읽는다 — 그 스크립트가 보는 설치 앱이 Django 의 것과 같아야 한다."""

    assert deps.installed_apps() == {app for app in settings.INSTALLED_APPS if not app.startswith("django.")}


def test_classroom_is_actually_installed():
    """#275 — 미리 분류만 해 두던 이름이 실제 앱으로 섰다. 강의실 ↮ 공모전 규칙이 저장소에서 발효된다."""

    assert "classroom" in settings.INSTALLED_APPS


# --- 합성 소스로 빨강을 고정한다 ---------------------------------------------------
#
# 한 번도 빨개지지 않는 검사는 통과하는 검사와 구별되지 않는다. 아래가 이 게이트가 실제로 문이라는 증거다.

KNOWN = frozenset({"core", "accounts", "storage", "submissions", "contests", "scoring", "classroom"})
CTX = deps.Context(
    known=KNOWN,
    settings_apps={"STORAGE_TARGET_RESOLVER": frozenset({"submissions"})},
    task_apps={"scoring.rescore": "scoring"},
)
TABLE = {
    "core": D("shared"),
    "accounts": D("shared", uses=frozenset({"core"})),
    "storage": D("shared", uses=frozenset({"core"})),
    "submissions": D("shared", uses=frozenset({"core", "storage"})),
    "contests": D("contest", uses=frozenset({"core", "accounts", "submissions"})),
    "scoring": D("contest", uses=frozenset({"core", "contests"})),
    "classroom": D("classroom", uses=frozenset({"core"})),
}


def _problems(source: str, app: str, table=TABLE, orm=()) -> list[str]:
    found = deps.classify(deps.file_couplings(source, app=app, path=f"{app}/x.py", ctx=CTX), table)
    return deps.problems(table, [*found, *orm], deps.markers(source), set(), orm_counted=False)


def _couplings(source: str, app: str) -> set[tuple[str, str, str]]:
    found = deps.classify(deps.file_couplings(source, app=app, path=f"{app}/x.py", ctx=CTX), TABLE)
    return {(c.src, c.dst, c.kind) for c in found}


def test_a_declared_import_passes():
    assert not _problems("from submissions.models import Submission\n", "contests")


def test_an_undeclared_import_is_red_even_inside_a_function():
    source = "def grade():\n    from scoring.services import score\n    return score\n"
    assert any("contests → scoring" in p for p in _problems(source, "contests"))


def test_an_import_under_type_checking_is_not_a_coupling():
    source = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from scoring.models import Score\n"
    assert not _problems(source, "contests")


def test_a_model_string_is_a_coupling():
    source = 'contest = models.ForeignKey("contests.Contest", on_delete=models.CASCADE)\n'
    assert any("classroom → contests" in p for p in _problems(source, "classroom"))


def test_a_dotted_path_to_another_apps_module_is_a_coupling():
    assert ("submissions", "contests", "uses") in _couplings('HANDLER = "contests.models.Contest"\n', "submissions")


def test_a_logger_name_and_a_slot_owner_are_not_couplings():
    source = 'log = logging.getLogger("contests.models")\nSLOT = Slot("이름", "contests.apps")\n'
    assert not _couplings(source, "submissions")


def test_a_celery_task_name_is_a_coupling():
    assert ("contests", "scoring", "uses") in _couplings('app.send_task("scoring.rescore")\n', "contests")


def test_registering_into_a_slot_plugs_into_the_owner():
    source = "from core.ports import SLOT\nSLOT.register(handler)\n"
    assert ("contests", "core", "plugs") in _couplings(source, "contests")


def test_a_register_function_plugs_into_its_app():
    source = "from core.scans import register_scan\nregister_scan(SPEC)\n"
    assert ("contests", "core", "plugs") in _couplings(source, "contests")


def test_connecting_to_a_signal_plugs_into_the_signal_owner():
    source = "from accounts.signals import user_withdrawn\nuser_withdrawn.connect(leave)\n"
    assert ("contests", "accounts", "plugs") in _couplings(source, "contests")


def test_a_receiver_decorator_plugs_into_the_signal_owner():
    source = "from accounts.signals import user_withdrawn\n@receiver(user_withdrawn)\ndef leave(**kw):\n    pass\n"
    assert ("contests", "accounts", "plugs") in _couplings(source, "contests")


def test_hooking_another_apps_model_saves_plugs_into_it():
    source = "from accounts.models import User\npost_save.connect(sync, sender=User)\n"
    assert ("contests", "accounts", "plugs") in _couplings(source, "contests")


def test_a_setting_read_below_that_points_above_is_a_plug_from_above():
    """`storage` 가 읽는 설정이 `submissions` 의 해석기를 가리키면, 저장소가 돌 때 제출 코드가 돈다."""

    assert ("submissions", "storage", "plugs") in _couplings("path = settings.STORAGE_TARGET_RESOLVER\n", "storage")
    assert any("submissions → storage" in p for p in _problems("p = settings.STORAGE_TARGET_RESOLVER\n", "storage"))


def test_an_undeclared_plug_is_red():
    source = "from core.scans import register_scan\nregister_scan(SPEC)\n"
    assert any("contests → core" in p for p in _problems(source, "contests"))


def test_an_exception_marker_is_red_even_with_a_reason():
    source = "from core.clock import Clock  # APP-BOUNDARY-EXCEPTION: 급해서\n"
    assert any("APP-BOUNDARY-EXCEPTION" in p for p in _problems(source, "contests"))


def test_mentioning_the_marker_in_prose_is_not_a_marker():
    assert not deps.markers('"""`APP-BOUNDARY-EXCEPTION` 과 같은 관용구다."""\n')


def test_a_cycle_is_red():
    table = {**TABLE, "core": D("shared", uses=frozenset({"accounts"}))}
    assert any(p.startswith("순환:") for p in deps.problems(table, [], [], set(), orm_counted=False))


def test_a_plug_upward_closes_a_cycle_too():
    """`plugs` 도 위 → 아래다 — 아래 앱이 위 앱에 꽂으면 층이 뒤집힌다."""

    table = {**TABLE, "core": D("shared", plugs=frozenset({"accounts"}))}
    assert any(p.startswith("순환:") for p in deps.problems(table, [], [], set(), orm_counted=False))


def test_the_shared_layer_cannot_declare_a_feature_app():
    table = {**TABLE, "accounts": D("shared", uses=frozenset({"core", "contests"}))}
    assert any("공유층이 기능 앱" in p for p in deps.problems(table, [], [], set(), orm_counted=False))


def test_classroom_and_the_contest_family_cannot_declare_each_other_in_any_column():
    for column in ("uses", "plugs"):
        table = {**TABLE, "classroom": D("classroom", **{column: frozenset({"contests"})})}
        assert any("강의실과 공모전" in p for p in deps.problems(table, [], [], set(), orm_counted=False)), column


def test_a_declaration_the_code_does_not_back_is_red():
    found = [deps.Coupling("contests", "core", "uses", "contests/x.py", 1, "import")]
    table = {"core": D("shared"), "contests": D("contest", uses=frozenset({"core", "accounts"})), "accounts": D("shared")}
    assert any("contests.uses 의 accounts" in p for p in deps.problems(table, found, [], set()))


def test_an_installed_app_missing_from_the_table_is_red():
    assert any("newapp: 표에 없다" in p for p in deps.problems(TABLE, [], [], {"newapp"}, orm_counted=False))


def test_an_orm_path_up_the_layers_is_red_and_has_no_column_to_hide_in():
    """아래 앱이 역관계로 위 앱의 행을 걷는다 — 안 적으면 선언 밖, uses 에 적으면 순환이다(#1102). 위 앱이 관계를 올린다."""

    orm = [deps.Coupling("contests", "scoring", "orm", "contests/x.py", 3, "ORM 경로 score")]
    red = _problems("", "contests", orm=orm)
    assert any("contests → scoring" in p and "NEXT_ACTION_RELATIONS" in p for p in red)
    table = {**TABLE, "contests": D("contest", uses=TABLE["contests"].uses | {"scoring"}, plugs=TABLE["contests"].plugs)}
    assert any(p.startswith("순환:") and "scoring" in p for p in _problems("", "contests", table=table, orm=orm))
    with pytest.raises(TypeError):
        D("contest", reads=frozenset({"scoring"}))  # type: ignore[call-arg]


def test_the_table_has_no_reads_column():
    assert all(set(entry) <= {"group", "uses", "plugs"} for entry in deps.tomllib.loads(deps.TABLE.read_text()).values())


def test_orm_paths_are_found_in_lookups_and_relation_arguments():
    import ast

    source = (
        'qs.filter(user__sponsor_profile__contests__created_at__lt=t)\n'
        'qs.select_related("score", "contest__award")\n'
        'Q(distribution__isnull=True)\n'
    )
    paths = {p for p, _, _ in deps.orm_paths(ast.parse(source))}
    assert {"user__sponsor_profile__contests__created_at__lt", "score", "contest__award", "distribution__isnull"} <= paths


def test_the_head_of_a_queryset_chain_names_the_start_model():
    import ast

    source = 'ContestSubmission.objects.filter(contest=c).select_related("score")\n'
    assert ("score", 1, "ContestSubmission") in deps.orm_paths(ast.parse(source))


def test_an_orm_path_counts_only_apps_every_plausible_start_walks_through():
    """`score__gte` 가 제 모델의 정수 칸일 수도 있으면 세지 않는다 — 오탐이 늘면 규칙이 신뢰를 잃는다."""

    walks = {"own": set(), "other": {"scoring"}}

    def resolve(starts, segs, root):
        return set.intersection(*walks.values())

    source = deps.Source("classroom", "classroom/x.py", "", __import__("ast").parse("qs.filter(score__gte=1)\n"))
    assert not deps.orm_couplings([source], TABLE, resolve)


# --- 바뀐 파일 → 다시 돌 앱 ---------------------------------------------------------


def test_a_change_reruns_the_app_and_everything_that_uses_it():
    assert deps.affected(["backend/contests/models.py"], TABLE) == {"contests", "scoring"}


def test_a_change_in_a_plugged_app_reruns_the_app_it_plugs_into():
    """`submissions` 가 `storage` 에 꽂혀 있으면 저장소 시험이 제출 코드를 돈다."""

    table = {**TABLE, "submissions": D("shared", uses=frozenset({"core"}), plugs=frozenset({"storage"}))}
    assert {"submissions", "storage"} <= deps.affected(["backend/submissions/resolvers.py"], table)


def test_a_plugged_app_reruns_alone_and_does_not_spread_to_its_users():
    """모든 기능 앱이 `core` 등록부에 꽂힌다 — 거기서 더 번지면 무엇을 바꿔도 전부가 된다."""

    table = {**TABLE, "scoring": D("contest", uses=TABLE["scoring"].uses, plugs=frozenset({"core"}))}
    picked = deps.affected(["backend/scoring/services.py"], table)
    assert "core" in picked and "accounts" not in picked


def test_project_wide_files_rerun_everything_and_frontend_reruns_nothing():
    assert deps.affected(["backend/config/settings.py"], TABLE) is None
    assert deps.affected(["backend/app_deps.toml"], TABLE) is None
    assert deps.affected(["frontend/app/page.tsx", "docs/ops/testing.md"], TABLE) == set()
