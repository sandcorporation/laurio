"""e2e 가 Playwright 를 돌릴 공식 이미지 — 판이 lockfile 의 `@playwright/test` 와 같을 때만 그 참조를 낸다(#1109).

    python3 scripts/ci/playwright_image.py   →  표준 출력에 이미지 참조 한 줄, 어긋나면 까닭을 stderr 에 내고 exit 1

참조는 `scripts/ci/playwright-image` 한 줄이 들고 있다: `mcr.microsoft.com/playwright:v<판>-<배포판>@sha256:<64자>`.
태그의 판과 `pnpm-lock.yaml` 의 `@playwright/test@<판>` 이 하나라도 다르면 실패한다 — 조용히 다른 판의 브라우저로 돌지
않게. 다이제스트가 없으면 실패한다(공개 저장소의 이미지는 다이제스트로 고정한다). `@playwright/test` 를 올리면 같은
판의 태그와 그 다이제스트로 이 파일도 고친다:

    curl -sI -H 'Accept: application/vnd.oci.image.index.v1+json' \\
      https://mcr.microsoft.com/v2/playwright/manifests/v<판>-noble | grep -i docker-content-digest
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF_FILE = ROOT / "scripts/ci/playwright-image"
LOCK_FILE = ROOT / "pnpm-lock.yaml"

REF = re.compile(r"^mcr\.microsoft\.com/playwright:v(?P<version>\d+\.\d+\.\d+)-[a-z]+@sha256:[0-9a-f]{64}$")
LOCK = re.compile(r"@playwright/test@(\d+\.\d+\.\d+)")


class Mismatch(Exception):
    """이미지 참조를 쓸 수 없다 — 까닭이 메시지다."""


def checked_ref(ref_text: str, lock_text: str) -> str:
    ref = ref_text.strip()
    m = REF.match(ref)
    if not m:
        raise Mismatch(f"이미지 참조 꼴이 아니다(mcr.microsoft.com/playwright:v<판>-<배포판>@sha256:<64자>): {ref!r}")
    locked = set(LOCK.findall(lock_text))
    if not locked:
        raise Mismatch("pnpm-lock.yaml 에 @playwright/test 판이 없다")
    if locked != {m["version"]}:
        raise Mismatch(f"이미지 판 {m['version']} ≠ lockfile 의 @playwright/test {', '.join(sorted(locked))} — scripts/ci/playwright-image 를 같은 판으로")
    return ref


def main() -> int:
    try:
        print(checked_ref(REF_FILE.read_text(encoding="utf-8"), LOCK_FILE.read_text(encoding="utf-8")))
    except Mismatch as e:
        print(f"Playwright 이미지: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
