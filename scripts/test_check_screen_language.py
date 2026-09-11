#!/usr/bin/env python3
"""`check_screen_language.py`의 내부 어휘 게이트를 고정한다(#308).

이 저장소의 `scripts/` 검사는 로컬 게이트가 아니라 CI 전용이다(`CLAUDE.md`
「앱 경계는 테스트가 지킨다」절 — `scripts/` 검사는 push 해야만 결과를 안다).
그래서 이 파일도 pytest가 아니라 표준 라이브러리 `unittest`로 쓴다 —
`python3 scripts/check_screen_language.py`처럼 스택도 의존성 설치도 없이
`python3 scripts/test_check_screen_language.py` 하나로 돈다.

실제로 걸렸던 예를 그대로 고정한다: `classroom/app/page.tsx`가 한때
`eyebrow="강의실"`을 썼고(#308 전 상태), 그 자리를 지금은 `클래스`로
고쳤다 — 그 리팩터를 되돌리면 이 테스트가 먼저 빨개진다.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import check_screen_language as csl


class InternalVocabTermsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.terms = csl.load_terms()
        self.internal_terms = [t for t in self.terms if t.internal_vocab]

    def test_internal_vocab_terms_are_loaded(self) -> None:
        names = {t.name for t in self.internal_terms}
        self.assertEqual(names, set(csl.INTERNAL_VOCAB))

    def test_bare_transition_particle_is_not_blocked(self) -> None:
        """`상태 전이`·`전이 그래프`만 막는다 — 바른 「마감 전이라」 문장이
        오탐되면 화면 문구를 정상적으로 쓸 수 없게 된다."""
        line = '          아직 마감 전이라 채점이 시작되지 않았습니다.'
        for term in self.internal_terms:
            self.assertIsNone(
                term.pattern.search(line),
                f"`{term.name}` 가 무해한 문장을 오탐했다: {line!r}",
            )


class CheckFileInternalVocabTest(unittest.TestCase):
    def setUp(self) -> None:
        self.terms = csl.load_terms()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def _write(self, contents: str) -> Path:
        path = Path(self.tmpdir.name) / "page.tsx"
        path.write_text(contents)
        return path

    def test_leaked_internal_vocab_is_flagged(self) -> None:
        path = self._write(
            'export const note = "이 값은 불변식을 유지합니다";\n'
        )
        problems = csl.check_file(path, self.terms)
        self.assertEqual(len(problems), 1)
        self.assertIn("불변식", problems[0])
        self.assertIn("내부 낱말", problems[0])

    def test_state_transition_compound_is_flagged(self) -> None:
        path = self._write(
            'export const note = "이 화면은 상태 전이를 보여줍니다";\n'
        )
        problems = csl.check_file(path, self.terms)
        self.assertEqual(len(problems), 1)
        self.assertIn("상태 전이", problems[0])

    def test_exception_marker_suppresses_internal_vocab(self) -> None:
        path = self._write(
            "\n".join(
                [
                    "// SCREEN-LANGUAGE-EXCEPTION: 개발자용 디버그 문자열이다",
                    'export const note = "이 값은 멱등하게 재시도됩니다";',
                ]
            )
        )
        problems = csl.check_file(path, self.terms)
        self.assertEqual(problems, [])

    def test_comment_only_mention_is_not_flagged(self) -> None:
        path = self._write(
            "\n".join(
                [
                    "// 이 컴포넌트는 스냅샷을 남기지 않는다.",
                    'export const note = "불러오는 중입니다";',
                ]
            )
        )
        problems = csl.check_file(path, self.terms)
        self.assertEqual(problems, [])

    def test_real_screens_have_no_internal_vocab_leak(self) -> None:
        """실제 화면 파일 전체를 훑어 회귀를 고정한다 — 새 화면이 다시
        설계 어휘를 쓰면 여기서 걸린다."""
        repo_root = csl.REPO_ROOT
        problems: list[str] = []
        for scan_dir in csl.SCAN_DIRS:
            base = repo_root / scan_dir
            for pattern in ("*.tsx", "*.ts"):
                for f in sorted(base.rglob(pattern)):
                    if csl._is_test(f):
                        continue
                    problems.extend(csl.check_file(f, self.terms))
        internal_problems = [p for p in problems if "내부 낱말" in p]
        self.assertEqual(internal_problems, [])


if __name__ == "__main__":
    unittest.main()
