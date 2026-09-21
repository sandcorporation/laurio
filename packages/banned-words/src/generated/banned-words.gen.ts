// 이 파일은 생성됩니다 — 손으로 고치지 마세요.
// `pnpm --dir packages/banned-words generate` 로 backend/core/banned_words.py 에서
// 다시 만듭니다(ADR-0051). CI가 이 파일이 최신인지 확인합니다(재생성 후 diff가 나면 실패).

/** 운영진을 사칭하는 낱말 — 이름에만 적용한다. 원본:
 * `backend/core/banned_words.py`의 `IMPERSONATION_WORDS`. */
export const IMPERSONATION_WORDS: readonly string[] = [
  "admin",
  "administrator",
  "codemit",
  "moderator",
  "operator",
  "staff",
  "관리자",
  "매니저",
  "스태프",
  "어드민",
  "운영자",
  "운영진",
];

/** 욕설 — 이름·제목·본문 어디든 적용한다. 원본:
 * `backend/core/banned_words.py`의 `PROFANITY_WORDS`. */
export const PROFANITY_WORDS: readonly string[] = [
  "asshole",
  "bitch",
  "fuck",
  "개새끼",
  "병신",
  "씨발",
  "씨팔",
  "좆같",
];
