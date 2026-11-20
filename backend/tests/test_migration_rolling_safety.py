"""겹쳐 바꾸는 배포의 마이그레이션 쪽 고정 (#526, ADR-0053).

**배포는 마이그레이션을 먼저 돌리고 backend·events 를 겹쳐 바꾼다.** `deploy.sh` 가 새
이미지의 일회성 컨테이너에서 `migrate` 를 돌린 뒤, 옛 컨테이너가 계속 요청을 받는 채로 새
것을 띄운다. 그 몇 초 동안 **옛 코드가 새 스키마 위에서 돈다.**

마이그레이션이 base(병합 대상) 코드와 호환되는지는 CI 의 static 묶음이
`scripts/ci/migration_compat.py` 로 본다(#1091, 시험은 `test_migration_compat.py`). 예전의 AST 규칙과
`ROLLING-DEPLOY-SAFE`·`GRANDFATHERED` 는 그 검사로 바뀌었다 — 이전 상태를 알아 사람의 표식이 필요 없다.
여기에는 배포 쪽 고정만 남는다.
"""

from __future__ import annotations

import yaml

from tests.ast_scan_support import BACKEND_ROOT

REPO_ROOT = BACKEND_ROOT.parent


def test_deployed_backend_does_not_migrate_on_boot():
    """migrate 는 deploy.sh 의 일회성 컨테이너 한 곳에서만 돈다.

    기동 command 에 남으면 겹쳐 바꾸는 동안 새 backend 가 스키마를 또 건드리고, 내리고 올리는
    배포에서는 옛 worker·beat·events 가 새 스키마 위에 남는다.
    """
    for target in ("prod",):
        compose = yaml.safe_load((REPO_ROOT / "docker" / f"compose.{target}.yaml").read_text(encoding="utf-8"))
        for service in ("backend", "celery-worker", "events"):
            command = compose["services"][service].get("command", "")
            command = " ".join(command) if isinstance(command, list) else command
            assert "migrate" not in command, f"compose.{target}.yaml 의 {service} 가 기동 때 migrate 를 돌린다"
