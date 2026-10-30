"""강의실과 공모전이 서로를 부르지 못한다는 것을 정적으로 고정한다 (#269, ADR-0037).

**ADR-0037 이 Classroom 을 별도 서비스로 가르지 않기로 하면서 진 빚이 이것이다.**
프로세스가 갈려 있으면 잘못된 import 는 애초에 컴파일되지 않는다. 한 프로세스 안에서는
`from contests.models import Contest` 한 줄이 그냥 돌아가고, 그 한 줄은 리뷰에서 가장 안
읽히는 종류다 — 특히 **함수 안 지연 import** 는 파일 최상단만 봐서는 존재조차 안 보인다.
그래서 기계가 매 커밋 확인한다.

**왜 `scripts/` 가 아니라 여기인가.** 티켓을 닫는 로컬 게이트는 `pytest`·두 앱
`typecheck`·브라우저 걷기 셋이다(`CLAUDE.md`). `scripts/` 검사는 그 셋 중 어디에도 안
걸려 push 해야만 결과를 안다. import 경계는 **쓰는 순간** 막혀야 뜻이 있다. 그리고 이
저장소에는 AST 게이트를 테스트로 두는 관용구가 이미 있다 — `ast_scan_support` 를
`test_contest_kind_gates`·`test_contest_transitions`·
`test_contest_status_writes_are_declared` 셋이 공유하고, `test_appeals.py` 에는 앱 간
import 금지를 AST 로 보는 테스트가 이미 하나 있다.

## 규칙이 둘이고 강도가 다르다

- **규칙 A — 강의실 ↮ 공모전 가족. 양방향, 예외 없음.** 최상단이든 함수 안이든,
  import 든 Django 의 문자열 참조(`ForeignKey("contests.Contest")`·`apps.get_model`)든
  걸린다. 여기에는 예외 표시가 **듣지 않는다** — 표시로 열 수 있는 문이 있으면 마감에
  몰린 사람이 그 문을 쓴다.
- **규칙 B — 공유층은 기능 앱을 보지 않는다. 예외 표시로 열린다.** 지금 있는 것들은
  순환을 끊으려고 일부러 함수 안에 넣은 지연 import 라 지우는 것이 이 티켓의 일이 아니다.
  대신 사유를 적어 표시한다 — 붙는 순간 `grep -rn "APP-BOUNDARY-EXCEPTION" backend/` 한
  줄로 세어지고, 그 숫자가 늘었는지 줄었는지가 이 경계의 건강 지표가 된다.

표시의 모양은 `scripts/check_screen_language.py` 의 관용구를 그대로 따른다 — 같은 줄이나
바로 앞 줄에 `APP-BOUNDARY-EXCEPTION: <이유>`, **이유가 비면 예외 자체가 실패한다.** 이유
없는 예외는 「일부러 남긴 것」과 「그냥 걸린 것」을 구별하지 못하게 만든다.

## 표가 `INSTALLED_APPS` 와 어긋나면 실패한다

한 방향으로만 그렇다 — 설치된 앱은 전부 분류돼 있어야 하지만, 표는 아직 설치되지 않은
앱을 미리 이름 지을 수 있다(`classroom` 이 #275 전까지 그런 자리였다). 그 한 방향이
새 앱을 만드는 사람에게 분류를 강제하는 장치다: 앱을 하나 더하면 표에 적기 전까지
빨갛다.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from tests.ast_scan_support import BACKEND_ROOT

#: 두 제품이 나눠 쓰는 층. 여기서 기능 앱으로 내려가는 것이 규칙 B 가 막는 방향이다.
#: `submissions`가 #270(ADR-0039)로 여기 합류했다 — `Submission`(부모)이 공모전을
#: 몰라야 강의실이 두 번째 자식(`ProblemSubmission`)을 붙일 수 있다. 공모전 전용
#: 코드(자식 모델·제출 API·「다음 행동」 판정·target_ref 조립·파기 스캔)는
#: `contests.submission_*`로 옮겨갔다 — 이 앱에는 부모·자료·근거·자가 응답과 그
#: 규칙만 남는다.
#: `ops_metrics`(#827)는 운영 지표의 1분 집계 — `core.llm_metrics` 가 부르고 기능 앱을 모른다.
SHARED = frozenset({"accounts", "core", "policies", "storage", "notifications", "submissions", "ops_metrics"})

#: 공모전 제품. `verification`(본인확인)과 `payments`·`ledger`·`payouts` 계열이 여기 있는
#: 이유는 강의실이 본인확인도 결제도 쓰지 않기로 했기 때문이다(ADR-0037).
CONTEST_FAMILY = frozenset(
    {
        "contests",
        "scoring",
        "repositories",
        "awards",
        "appeals",
        "payments",
        "ledger",
        "payouts",
        "distributions",
        "handovers",
        "verification",
    }
)

#: 강의실. #275 로 섰다 — 모델은 아직 없다.
CLASSROOM = frozenset({"classroom"})

FEATURE_APPS = CONTEST_FAMILY | CLASSROOM
CLASSIFIED_APPS = SHARED | FEATURE_APPS

EXCEPTION_RE = re.compile(r"APP-BOUNDARY-EXCEPTION:\s*(.*)$")

#: Django 가 import 없이 앱을 묶는 길 — `ForeignKey("contests.Contest")` 꼴. 점 하나로
#: 갈리고 양쪽이 식별자인 것만 본다. 긴 docstring 안의 `contests.models.Contest` 같은
#: 언급은 문자열 전체가 이 모양이 아니라 저절로 빠진다.
MODEL_REF_RE = re.compile(r"^([a-z_][a-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)$")


@dataclass(frozen=True)
class Reference:
    """한 파일이 다른 앱을 가리키는 한 지점."""

    line: int
    app: str
    detail: str
    #: import 가 아니라 문자열로 가리키는 것 — 규칙 A 만 이것을 본다.
    by_string: bool = False


def _module_app(module: str) -> str:
    return module.split(".", 1)[0]


def references(source: str, tree: ast.AST | None = None) -> list[Reference]:
    """소스 하나가 다른 앱을 가리키는 지점 전부. 파일을 읽지 않는다 — 합성 소스로
    빨강을 고정할 수 있어야 하기 때문이다(한 번도 빨개지지 않는 검사는 통과하는 검사와
    구별되지 않는다)."""

    tree = tree if tree is not None else ast.parse(source)
    found: list[Reference] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                app = _module_app(alias.name)
                if app in CLASSIFIED_APPS:
                    found.append(Reference(node.lineno, app, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            # `from .models import X` 는 같은 앱이다 — level > 0 이면 건너뛴다.
            if node.level == 0 and node.module:
                app = _module_app(node.module)
                if app in CLASSIFIED_APPS:
                    found.append(Reference(node.lineno, app, f"from {node.module} import ..."))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            m = MODEL_REF_RE.match(node.value)
            if m and m.group(1) in CLASSIFIED_APPS:
                found.append(
                    Reference(node.lineno, m.group(1), f'문자열 참조 "{node.value}"', by_string=True)
                )
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "get_model" and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and first.value in CLASSIFIED_APPS:
                    found.append(
                        Reference(
                            node.lineno,
                            first.value,
                            f'get_model("{first.value}", ...)',
                            by_string=True,
                        )
                    )

    return found


def _exception_markers(source: str) -> tuple[dict[int, str], dict[int, str]]:
    """(표시가 적힌 줄 → 사유, 그 표시가 덮는 줄 → 사유).

    둘을 가르는 이유는 사유가 빈 표시를 **표시가 적힌 줄에서 한 번만** 보고하기
    위해서다 — 덮는 줄까지 세면 표시 하나가 실패 둘로 보인다.
    """

    markers: dict[int, str] = {}
    covers: dict[int, str] = {}
    for i, line in enumerate(source.split("\n"), 1):
        m = EXCEPTION_RE.search(line)
        if m is None:
            continue
        reason = m.group(1).strip()
        markers[i] = reason
        covers[i] = reason
        covers.setdefault(i + 1, reason)
    return markers, covers


def app_of(path: Path) -> str | None:
    """이 파일이 어느 앱의 것인가. `config/` 나 `manage.py` 처럼 앱이 아닌 것은 None —
    조립 지점은 모두를 알아야 하므로 경계의 대상이 아니다."""

    parts = path.relative_to(BACKEND_ROOT).parts
    return parts[0] if len(parts) > 1 and parts[0] in CLASSIFIED_APPS else None


def violations(source: str, *, app: str, tree: ast.AST | None = None) -> list[str]:
    """`app` 에 속한 소스 하나의 경계 위반 전부. 사람이 읽을 문장으로 돌려준다."""

    markers, covers = _exception_markers(source)
    problems: list[str] = []

    for line in sorted(line for line, reason in markers.items() if not reason):
        problems.append(f"{line}줄: 예외 표시에 이유가 없다 — `APP-BOUNDARY-EXCEPTION: <이유>`")

    for ref in references(source, tree):
        if ref.app == app:
            continue

        crosses_rule_a = (app in CLASSROOM and ref.app in CONTEST_FAMILY) or (
            app in CONTEST_FAMILY and ref.app in CLASSROOM
        )
        if crosses_rule_a:
            problems.append(
                f"{ref.line}줄: 강의실과 공모전은 서로를 부를 수 없다 — "
                f"{app} → {ref.app} ({ref.detail}). "
                f"예외 표시로 열리지 않는다: 공유층으로 옮기거나 각자 갖는다 (ADR-0037)"
            )
            continue

        if ref.by_string:
            # 문자열 참조는 규칙 A 만 본다 — 공유층 전반에 걸면 오탐이 늘어 규칙이
            # 신뢰를 잃는다.
            continue

        if app in SHARED and ref.app in FEATURE_APPS:
            if covers.get(ref.line):
                continue
            problems.append(
                f"{ref.line}줄: 공유층이 기능 앱을 부른다 — {app} → {ref.app} ({ref.detail}). "
                f"정말 어쩔 수 없으면 같은 줄이나 앞 줄에 "
                f"`APP-BOUNDARY-EXCEPTION: <이유>` 를 남긴다"
            )

    return problems


def _scan_repository(sources) -> list[str]:
    """`sources` 는 세션 픽스처 `backend_sources`(이미 읽고 파싱한 소스 전부)다."""

    reported: list[str] = []
    for source in sources:
        app = app_of(BACKEND_ROOT / source.relative)
        if app is None:
            continue
        for problem in violations(source.text, app=app, tree=source.tree):
            reported.append(f"{source.relative}:{problem}")
    return reported


# --- 저장소 전체 -----------------------------------------------------------------


def test_the_boundary_holds_across_the_repository(backend_sources):
    """지금 저장소가 이 표를 지킨다. 실패 메시지가 어느 파일 어느 줄인지와 무엇을 해야
    하는지를 말한다 — 규칙만 있고 길이 없으면 다음 사람이 표에서 규칙을 지운다."""

    problems = _scan_repository(backend_sources)
    assert not problems, "앱 경계 위반:\n" + "\n".join(problems)


def test_every_installed_app_is_classified():
    """앱을 하나 더하면 표에 적기 전까지 빨갛다 — 이것이 강의실을 만드는 사람에게 분류를
    강제하는 장치다. 반대 방향은 보지 않는다: 표는 아직 설치되지 않은 앱을 미리 이름
    지을 수 있다."""

    installed = {
        app for app in settings.INSTALLED_APPS if not app.startswith("django.contrib.")
    }
    unclassified = sorted(installed - CLASSIFIED_APPS)
    assert not unclassified, (
        f"이 앱들이 어느 쪽인지 정해지지 않았다: {unclassified} — "
        f"tests/test_app_boundaries.py 의 SHARED·CONTEST_FAMILY·CLASSROOM 중 하나에 적는다"
    )


def test_the_three_groups_do_not_overlap():
    assert not (SHARED & CONTEST_FAMILY)
    assert not (SHARED & CLASSROOM)
    assert not (CONTEST_FAMILY & CLASSROOM)


def test_classroom_is_actually_installed():
    """#275 — 미리 분류만 해 두던 이름이 실제 앱으로 섰다. 이제부터는 규칙 A 가
    합성 소스가 아니라 저장소 자체에서도 발효된다."""

    assert "classroom" in settings.INSTALLED_APPS


# --- 합성 소스로 빨강을 고정한다 ---------------------------------------------------
#
# 한 번도 빨개지지 않는 검사는 통과하는 검사와 구별되지 않는다. 아래가 이 게이트가 실제로
# 문이라는 증거다.


def test_classroom_cannot_import_the_contest_family_at_module_level():
    assert violations("from contests.models import Contest\n", app="classroom")


def test_classroom_cannot_hide_the_import_inside_a_function():
    source = "def grade():\n    from scoring.services import score\n    return score\n"
    assert violations(source, app="classroom")


def test_the_contest_family_cannot_import_classroom_either():
    """양방향이다 — 한쪽만 막으면 반대쪽에서 새고, 그쪽이 더 눈에 안 띈다."""

    assert violations("import classroom.models\n", app="contests")


def test_classroom_cannot_bind_to_a_contest_model_by_string():
    """import 없이 두 도메인이 스키마 수준에서 영구히 묶이는 유일한 길."""

    source = 'contest = models.ForeignKey("contests.Contest", on_delete=models.CASCADE)\n'
    assert violations(source, app="classroom")


def test_classroom_cannot_reach_a_contest_model_through_get_model():
    assert violations('apps.get_model("contests", "Contest")\n', app="classroom")


def test_the_contest_family_cannot_bind_to_a_classroom_model_by_string_either():
    """오늘 실제로 열려 있는 방향은 이쪽이다 — 강의실 앱은 아직 없고, 공모전 코드가
    먼저 그쪽을 가리킬 수 있다."""

    source = 'problem = models.ForeignKey("classroom.Problem", on_delete=models.CASCADE)\n'
    assert violations(source, app="contests")


def test_the_shared_layer_needs_a_marker_for_classroom_too():
    """규칙 B 는 공모전 가족뿐 아니라 강의실에도 걸린다 — 공유층은 어느 제품도 모른다."""

    assert violations("from classroom.models import Class\n", app="core")


def test_an_exception_marker_does_not_open_the_classroom_boundary():
    """규칙 A 에는 문이 없다. 표시가 있어도 실패한다."""

    source = "from contests.models import Contest  # APP-BOUNDARY-EXCEPTION: 급해서\n"
    assert violations(source, app="classroom")


def test_the_shared_layer_cannot_reach_a_feature_app_without_a_marker():
    assert violations("from contests.models import Contest\n", app="accounts")


def test_a_marker_with_a_reason_opens_the_shared_layer_rule():
    source = "from contests.models import Contest  # APP-BOUNDARY-EXCEPTION: 탈퇴 자격 검사\n"
    assert not violations(source, app="accounts")


def test_a_marker_on_the_preceding_line_also_counts():
    source = (
        "# APP-BOUNDARY-EXCEPTION: 탈퇴 자격 검사\n"
        "from contests.models import Contest\n"
    )
    assert not violations(source, app="accounts")


def test_a_marker_without_a_reason_fails_on_its_own():
    """이유 없는 예외는 「일부러 남긴 것」과 「그냥 걸린 것」을 구별하지 못하게 만든다."""

    source = "from contests.models import Contest  # APP-BOUNDARY-EXCEPTION:\n"
    problems = violations(source, app="accounts")
    assert any("이유가 없다" in p for p in problems)


def test_the_shared_layer_may_use_the_shared_layer():
    assert not violations("from core.clock import Clock\n", app="accounts")


def test_a_feature_app_may_use_the_shared_layer():
    assert not violations("from accounts.models import DeveloperProfile\n", app="contests")


def test_the_contest_family_may_still_call_itself():
    """공모전 가족 내부는 검사하지 않는다 — 그 그물은 이미 촘촘하고 푸는 것이 이 경계의
    목적이 아니다."""

    assert not violations("from submissions.models import Submission\n", app="contests")


def test_relative_imports_are_the_same_app():
    assert not violations("from .models import Withdrawal\n", app="accounts")
