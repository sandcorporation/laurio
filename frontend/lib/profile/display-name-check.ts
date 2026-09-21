// 개최자 공개용 이름·개발자 표시 이름을 제출하기 전에 미리 검사한다(spec #474,
// #478) — `/console/profile`(app/console/profile/profile-page-client.tsx)이
// 두 역할(sponsor·developer) 모두에 이 함수를 제출을 누르는 순간에만 부른다
// (타이핑 중에는 부르지 않는다). 백엔드가 진짜 문이다(backend/accounts/api.py의
// `_reject_if_banned_display_name`, #478) — 이 검사는 편의일 뿐이라 화면을
// 건너뛰고 API를 직접 쳐도 서버가 그대로 막는다. 문구는 서버가 거절할 때 쓰는
// 것과 같다 — 둘이 어긋나면 고쳤는데도 또 막힌 것처럼 보인다. classroom의
// `lib/members/display-name-check.ts`(#476)와 같은 모양이다.
import { findBannedWordViolation } from "@codemit/banned-words";

export function checkDisplayNameForBannedWords(value: string): string | null {
  const violation = findBannedWordViolation(value, { checkImpersonation: true });
  if (violation === "impersonation") return "이름에는 운영진을 뜻하는 말을 쓸 수 없습니다.";
  if (violation === "profanity") return "이름에 욕설을 쓸 수 없습니다.";
  return null;
}
