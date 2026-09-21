// 클래스 이름·문제 제목·설명·체크리스트 항목을 제출하기 전에 미리 검사한다
// (spec #474, #479). 만들기·설정·문제 편집 화면이 제출을 누르는 순간에만
// 이 함수를 부른다(타이핑 중에는 부르지 않는다). 백엔드가 진짜 문이다
// (backend/classroom/api.py의 `_reject_if_banned_public_text`) — 이 검사는
// 편의일 뿐이라 화면을 건너뛰고 API를 직접 쳐도 서버가 그대로 막는다.
//
// **사칭 목록은 걸지 않는다** — 「관리자 페이지 만들기」는 정당한 문제
// 제목이다(spec #474 Implementation Decisions). 이름 필드
// (`checkDisplayNameForBannedWords`, lib/members/display-name-check.ts)와
// 갈리는 지점이 이것이다.
import { findBannedWordViolation } from "@codemit/banned-words";

export function checkPublicTextForBannedWords(value: string, fieldLabel: string): string | null {
  const violation = findBannedWordViolation(value, { checkImpersonation: false });
  if (violation === "profanity") return `${fieldLabel}에 욕설을 쓸 수 없습니다.`;
  return null;
}
