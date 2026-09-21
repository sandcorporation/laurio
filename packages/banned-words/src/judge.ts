// 금칙어 판정 순수 함수(spec #474, #476) — `backend/core/banned_words.py`의
// `find_banned_word_violation`을 그대로 옮겨 쓴 것이다. 목록은 생성물(ADR-0051)
// 이지만 이 알고리즘은 손으로 다시 쓴다 — 목록과 알고리즘이 같으면 결과가 같다는
// 것은 알고리즘 자체가 보장하고, "같은 입력에 같은 판정"(#476 AC)은 아래
// judge.test.ts가 백엔드 pytest(tests/test_classroom_banned_words.py)와 같은
// 대표 입력으로 고정한다.
//
// 판정은 **단순 포함**이다 — 대소문자를 무시하고 문자열에 그 낱말이 그대로
// 들어 있는가만 본다. **우회 표기(ㅅㅂ·시1발·시 발)는 일부러 잡지 않는다** —
// 쫓으면 정상 문장이 붙어 생기는 오탐이 새로 생기고, 사칭은 우회하는 순간 그
// 효과 자체가 없어진다.
import { IMPERSONATION_WORDS, PROFANITY_WORDS } from "./generated/banned-words.gen";

export type BannedWordViolation = "impersonation" | "profanity";

export function findBannedWordViolation(
  value: string,
  options: { checkImpersonation: boolean },
): BannedWordViolation | null {
  if (!value) return null;
  const lowered = value.toLowerCase();
  if (options.checkImpersonation && IMPERSONATION_WORDS.some((word) => lowered.includes(word))) {
    return "impersonation";
  }
  if (PROFANITY_WORDS.some((word) => lowered.includes(word))) {
    return "profanity";
  }
  return null;
}
