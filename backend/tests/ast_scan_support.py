"""AST 기반 게이트 테스트가 공유하는 파일 목록 (#256 코드리뷰).

`test_contest_kind_gates.py`(#232)·`test_contest_transitions.py`(#255)·
`test_contest_status_writes_are_declared.py`(#256) 셋이 「backend/ 전체에서
마이그레이션·테스트·venv·캐시를 뺀 .py 전부를 훑는다」는 같은 목록을 각자
복사해 갖고 있었다 — 스킵할 디렉터리가 하나 늘 때 셋 중 하나만 고쳐질
위험이 있었다. 여기 한 곳으로 모은다.

이 파일은 `test_` 로 시작하지 않으므로 pytest 가 수집하지 않는다(이미 이
디렉터리의 `tests/submission_assets.py` 가 같은 관용구다).
"""

from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent

#: 검사에서 빼는 경로. 마이그레이션은 과거의 스냅샷이고, 테스트는 픽스처를 자유롭게
#: 조립한다(예: `tests/test_status_classification.py` 가 모든 status 에 대한 답을
#: 리터럴로 고정하는 것처럼, 테스트 코드 자체가 검증 대상이지 이 스캔의 대상이 아니다).
SKIPPED_PARTS = {".venv", "migrations", "tests", "__pycache__"}


def python_sources(root: Path = BACKEND_ROOT) -> list[Path]:
    return [
        path
        for path in root.rglob("*.py")
        if not SKIPPED_PARTS & set(path.relative_to(root).parts)
    ]
