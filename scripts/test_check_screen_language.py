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



class MetaPhraseTest(unittest.TestCase):
    """화면이 자기 구현을 설명하는 문장을 막는다(2026-09-21).

    약관·방침의 첫 판이 「…는 8절에 자리만 남겨 두었고, 기능을 열 때 채웁니다」
    처럼 **문서가 자기 자신을 설명하는** 문장을 싣고 있었다. 사용자가 읽는
    화면은 지금 참인 사실만 말한다.
    """

    def _problems(self, source: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.tsx"
            path.write_text(source, encoding="utf-8")
            return csl.check_file(path, csl.load_terms())

    def test_placeholder_sentence_is_blocked(self) -> None:
        source = '<p>그 조항은 8절에 자리만 남겨 두었고, 기능을 열 때 채웁니다.</p>\n'
        problems = self._problems(source)
        self.assertTrue(problems, "자리 표시 문장이 통과했다")
        self.assertIn("자기 구현을 설명하는 문장", problems[0])

    def test_ordinary_sentence_is_not_blocked(self) -> None:
        """「자리」·「채우」가 들어간 정상 문구는 통과해야 한다."""
        source = '<p>남은 자리가 없습니다. 빈 칸을 채우고 다시 시도해주세요.</p>\n'
        self.assertEqual(self._problems(source), [])

    def test_exception_marker_opens_it(self) -> None:
        source = (
            "{/* SCREEN-LANGUAGE-EXCEPTION: 운영자에게만 보이는 안내다 */}\n"
            "<p>이 값은 아직 구현되지 않았습니다.</p>\n"
        )
        self.assertEqual(self._problems(source), [])


if __name__ == "__main__":
    unittest.main()
