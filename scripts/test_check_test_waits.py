#!/usr/bin/env python3
"""`check_test_waits.py` 가 막을 것을 막고 정당한 것은 통과시키는지 고정한다(#808).

`python3 scripts/test_check_test_waits.py` 하나로 돈다.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_test_waits as ctw  # noqa: E402


def found(path: str, source: str) -> int:
    return len(ctw.check_text(path, source))


class CheckTestWaits(unittest.TestCase):
    def test_blocks_fixed_waits_in_e2e(self) -> None:
        for line in [
            "await page.waitForTimeout(500);",
            "await page.waitForLoadState('networkidle');",
            "await page.waitForFunction(() => true);",
            "await expect(async () => {}).toPass();",
            "await expect.poll(() => 1).toBe(1);",
            "await new Promise((r) => setTimeout(r, 10));",
            "while (n < 3) { n += 1; }",
        ]:
            self.assertEqual(found("frontend/e2e/x.spec.ts", line), 1, line)

    def test_while_only_in_e2e(self) -> None:
        self.assertEqual(found("classroom/lib/x.test.ts", "while (stack.length) {}"), 0)

    def test_blocks_timers_in_unit_tests(self) -> None:
        self.assertEqual(found("operator/lib/x.test.ts", "const s = (ms) => new Promise((r) => setTimeout(r, ms));"), 1)

    def test_allows_test_timeout_limit_comments_and_strings(self) -> None:
        for line in [
            "test.setTimeout(30_000);",
            "// setTimeout(() => x(), 10) 는 쓰지 않는다",
            ' * waitForTimeout 을 쓰지 않는다',
            'const TIMERS = new Set(["setTimeout", "setInterval"]);',
            'expect(seeds("setTimeout(() => go(), 100);")).toBe(true);',
            "const x = 1; // waitForTimeout 아님",
        ]:
            self.assertEqual(found("frontend/e2e/x.spec.ts", line), 0, line)

    def test_exception_needs_reason(self) -> None:
        ok = "// TEST-WAIT-EXCEPTION: 고장 주입이다\nsetTimeout(() => go(), 10);\n"
        same = "setTimeout(() => go(), 10); // TEST-WAIT-EXCEPTION: 고장 주입이다\n"
        empty = "// TEST-WAIT-EXCEPTION:\nsetTimeout(() => go(), 10);\n"
        self.assertEqual(found("a.test.ts", ok), 0)
        self.assertEqual(found("a.test.ts", same), 0)
        self.assertEqual(found("a.test.ts", empty), 1)


if __name__ == "__main__":
    unittest.main()
