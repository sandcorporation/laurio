"""마이그레이션이 겹쳐 바꾸는 배포를 견디는지 정적으로 고정한다 (#526, ADR-0053).

**배포는 마이그레이션을 먼저 돌리고 backend·events 를 겹쳐 바꾼다.** `deploy.sh` 가 새
이미지의 일회성 컨테이너에서 `migrate` 를 돌린 뒤, 옛 컨테이너가 계속 요청을 받는 채로 새
것을 띄운다. 그 몇 초 동안 **옛 코드가 새 스키마 위에서 돈다.** 그래서 마이그레이션은 뒤로
호환되어야 한다 — 추가는 그대로 하고, 옛 코드가 아직 읽거나 쓰는 것을 지우거나 바꾸는 일은
다음 배포로 나눈다(expand → contract).

예전에는 새 마이그레이션이 든 배포가 전부 backend 를 내리고 올렸고, 그 창이 공개 앱의
재시도 예산(약 15.8초)보다 길어 `/contests` 가 500 을 냈다(2026-10-02 prod,
`0014_connected_apps` — GlitchTip 75·83).

## 위험한 연산과 두 표식

옛 코드를 깨뜨릴 수 있는 연산(아래 `_risks`)이 든 마이그레이션 파일은 둘 중 하나를 단다.
모양은 `APP-BOUNDARY-EXCEPTION`·`SCREEN-LANGUAGE-EXCEPTION` 과 같다 — 주석 한 줄,
**이유가 비면 표식 자체가 실패한다.**

- `# ROLLING-DEPLOY-UNSAFE: <이유>` — 정말 호환되지 않는다. `deploy.sh plan` 이 이 표식을
  배포 범위에서 찾으면 겹쳐 바꾸지 않고 넷을 내리고 올린다(몇 초~십수 초 backend 가 없다).
- `# ROLLING-DEPLOY-SAFE: <이유>` — 들여다봤고 옛 코드가 견딘다(예: 옛 코드가 이미 안 쓰는
  필드를 지우는 contract 단계, choices 만 바뀐 AlterField). 배포는 그대로 겹쳐 바꾼다.

AST 로 볼 수 있는 범위만 본다 — AlterField 가 정말 NOT NULL 을 더하는지는 이전 상태를
알아야 해서, `null=True` 가 아닌 AlterField 는 전부 사람이 보게 한다. 거짓 양성의 대가는
표식 한 줄이고, 거짓 음성의 대가는 배포 중 500 이다.

## 이미 적용된 옛 마이그레이션

`GRANDFATHERED` 는 이 규칙이 생기기 전(#526)에 쓰여 staging·prod 에 이미 적용된 파일이다.
대부분 `0002_initial` 의 순환을 끊는 AddField 다. 새 파일을 여기 더하지 않는다 — 표식을
단다. 표가 저장소와 어긋나면(지워진 파일이 남으면) 실패한다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml

from tests.ast_scan_support import BACKEND_ROOT

REPO_ROOT = BACKEND_ROOT.parent

#: `deploy.sh` 의 `UNSAFE_MIGRATION_MARKER` 와 같은 모양이다 — 주석 줄의 맨 앞.
UNSAFE = re.compile(r"^\s*#\s*ROLLING-DEPLOY-UNSAFE:(.*)$", re.MULTILINE)
SAFE = re.compile(r"^\s*#\s*ROLLING-DEPLOY-SAFE:(.*)$", re.MULTILINE)

#: 옛 코드가 읽거나 쓰는 것을 없애거나 바꾸는 연산 — 언제나 사람이 본다.
ALWAYS_RISKY = {
    "RemoveField": "컬럼을 지운다 — 옛 코드가 SELECT 에 그 컬럼을 넣는다",
    "DeleteModel": "테이블을 지운다",
    "RenameField": "컬럼 이름을 바꾼다 — 옛 코드는 옛 이름을 찾는다",
    "RenameModel": "테이블 이름을 바꾼다",
    "AlterModelTable": "테이블 이름을 바꾼다",
    "RunSQL": "무엇을 하는지 AST 로 알 수 없다",
}

#: #526 전에 쓰여 이미 적용된 파일 — 이유: 규칙이 생기기 전이고 되돌릴 수 없다.
GRANDFATHERED = frozenset(
    {
        "accounts/migrations/0002_socialaccount_nickname.py",
        "accounts/migrations/0003_social_account_email_verified_and_account_link.py",
        "accounts/migrations/0004_unique_non_empty_user_email.py",
        "appeals/migrations/0002_initial.py",
        "awards/migrations/0002_initial.py",
        "awards/migrations/0003_initial.py",
        "classroom/migrations/0002_initial.py",
        "classroom/migrations/0003_submission_formats.py",
        "classroom/migrations/0004_class_openai_api_key_status.py",
        "classroom/migrations/0005_grading_guideline.py",
        "classroom/migrations/0006_template_grading_guideline.py",
        "classroom/migrations/0007_class_default_model.py",
        "classroom/migrations/0008_reasoning_effort.py",
        "classroom/migrations/0010_alter_problem_status.py",
        "classroom/migrations/0011_syntax_check_enabled.py",
        "classroom/migrations/0012_syntax_check_toggle.py",
        "contests/migrations/0002_initial.py",
        "contests/migrations/0004_contest_is_free.py",
        "contests/migrations/0006_contest_view_count.py",
        "distributions/migrations/0002_initial.py",
        "handovers/migrations/0002_initial.py",
        "notifications/migrations/0002_alter_notification_notification_type_and_more.py",
        "notifications/migrations/0003_alter_notification_notification_type_and_more.py",
        "notifications/migrations/0004_operatornotice_image_object_key.py",
        "notifications/migrations/0005_alter_notification_notification_type_and_more.py",
        "repositories/migrations/0002_initial.py",
        "scoring/migrations/0002_initial.py",
        "submissions/migrations/0002_initial.py",
    }
)


def _migration_files() -> list[Path]:
    return sorted(
        path
        for path in BACKEND_ROOT.glob("*/migrations/*.py")
        if path.name != "__init__.py" and ".venv" not in path.parts
    )


def _op_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _kwarg(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _is_true(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _field_call(op: ast.Call) -> ast.Call | None:
    field = _kwarg(op, "field")
    if field is None and len(op.args) >= 3:
        field = op.args[2]
    return field if isinstance(field, ast.Call) else None


def _risks(source: str) -> list[str]:
    """그 파일에서 옛 코드를 깨뜨릴 수 있는 연산을 「줄: 연산 — 이유」로 돌려준다."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = _op_name(node)
        if name in ALWAYS_RISKY:
            found.append(f"{node.lineno}: {name} — {ALWAYS_RISKY[name]}")
        elif name in {"AddField", "AlterField"}:
            field = _field_call(node)
            if field is None:
                found.append(f"{node.lineno}: {name} — 필드를 읽을 수 없다")
                continue
            if _op_name(field) == "ManyToManyField":
                # 컬럼이 아니라 사이 테이블이다 — 옛 코드는 그 테이블을 모른다.
                continue
            if _is_true(_kwarg(field, "null")):
                continue
            if name == "AddField" and _kwarg(field, "db_default") is not None:
                continue
            if name == "AddField":
                found.append(
                    f"{node.lineno}: AddField — NOT NULL 컬럼을 DB 기본값 없이 더한다 "
                    "(옛 코드의 INSERT 가 그 컬럼을 빼먹는다 — null=True 나 db_default 를 쓴다)"
                )
            else:
                found.append(
                    f"{node.lineno}: AlterField — null 을 막거나 타입을 바꿀 수 있다(이전 상태를 보고 판단한다)"
                )
    return found


def _relative(path: Path) -> str:
    return path.relative_to(BACKEND_ROOT).as_posix()


def test_risky_migrations_carry_a_rolling_deploy_marker():
    offenders = []
    for path in _migration_files():
        rel = _relative(path)
        if rel in GRANDFATHERED:
            continue
        source = path.read_text(encoding="utf-8")
        if UNSAFE.search(source) or SAFE.search(source):
            continue
        risks = _risks(source)
        if risks:
            offenders.append(f"{rel}\n    " + "\n    ".join(risks))
    assert not offenders, (
        "옛 코드가 새 스키마 위에서 몇 초 도는 배포를 깨뜨릴 수 있는 마이그레이션이다(ADR-0053).\n"
        "뒤로 호환되게 나누거나(expand → contract), 파일에 표식을 단다:\n"
        "  # ROLLING-DEPLOY-UNSAFE: <이유>   — 배포가 넷을 내리고 올린다\n"
        "  # ROLLING-DEPLOY-SAFE: <이유>     — 들여다봤고 옛 코드가 견딘다\n\n" + "\n".join(offenders)
    )


def test_markers_have_a_reason_and_do_not_contradict():
    problems = []
    for path in _migration_files():
        source = path.read_text(encoding="utf-8")
        unsafe = [m.group(1).strip() for m in UNSAFE.finditer(source)]
        safe = [m.group(1).strip() for m in SAFE.finditer(source)]
        if any(not reason for reason in unsafe + safe):
            problems.append(f"{_relative(path)}: 이유가 빈 표식")
        if unsafe and safe:
            problems.append(f"{_relative(path)}: UNSAFE 와 SAFE 가 함께 있다 — 하나만 단다")
    assert not problems, "\n".join(problems)


def test_grandfathered_files_still_exist():
    missing = sorted(rel for rel in GRANDFATHERED if not (BACKEND_ROOT / rel).is_file())
    assert not missing, f"GRANDFATHERED 에 더는 없는 파일이 남았다 — 표에서 지운다: {missing}"


def test_deploy_script_reads_the_same_marker():
    """표식 문자열이 갈리면 시험은 초록인데 배포는 표식을 못 찾고 겹쳐 바꾼다."""
    deploy = (REPO_ROOT / "deploy.sh").read_text(encoding="utf-8")
    assert "UNSAFE_MIGRATION_MARKER='^[[:space:]]*#[[:space:]]*ROLLING-DEPLOY-UNSAFE:'" in deploy


def test_deployed_backend_does_not_migrate_on_boot():
    """migrate 는 deploy.sh 의 일회성 컨테이너 한 곳에서만 돈다.

    기동 command 에 남으면 겹쳐 바꾸는 동안 새 backend 가 스키마를 또 건드리고, 내리고 올리는
    배포에서는 옛 worker·beat·events 가 새 스키마 위에 남는다.
    """
    for target in ("prod",):
        compose = yaml.safe_load((REPO_ROOT / "docker" / f"compose.{target}.yaml").read_text(encoding="utf-8"))
        for service in ("backend", "celery-worker", "celery-beat", "events"):
            command = compose["services"][service].get("command", "")
            command = " ".join(command) if isinstance(command, list) else command
            assert "migrate" not in command, f"compose.{target}.yaml 의 {service} 가 기동 때 migrate 를 돌린다"


def test_unsafe_marker_is_seen_by_the_rule():
    """표식과 위험 판정이 실제로 맞물리는지 — 합성 소스로."""
    risky = "from django.db import migrations\nops = [migrations.RemoveField(model_name='x', name='y')]\n"
    assert _risks(risky)
    marked = "# ROLLING-DEPLOY-UNSAFE: y 를 지운다 — 옛 코드가 읽는다\n" + risky
    assert UNSAFE.search(marked)
    nullable = (
        "from django.db import migrations, models\n"
        "ops = [migrations.AddField(model_name='x', name='y', field=models.CharField(max_length=3, null=True))]\n"
    )
    assert not _risks(nullable)
    not_null = (
        "from django.db import migrations, models\n"
        "ops = [migrations.AddField(model_name='x', name='y', field=models.BooleanField(default=False))]\n"
    )
    assert _risks(not_null)
    db_default = (
        "from django.db import migrations, models\n"
        "ops = [migrations.AddField(model_name='x', name='y', field=models.BooleanField(db_default=False))]\n"
    )
    assert not _risks(db_default)
