// 템플릿 응답 하나에서 **지금 살아 있는 템플릿**을 읽는 순수 함수(2026-09-16).
//
// 이 한 줄이 없어서 버그가 하나 살았다: 문제 화면과 클래스 설정 카드가 공개·내리기
// 응답을 `{ share_code, taken_down }` 그대로 들고 있었고, 화면은 「그 값이 null 이
// 아니면 공개 폼을 감춘다」로 그렸다. 내리면 `taken_down: true` 라 **null 이 아니어서**
// 공개 폼이 돌아오지 않았고, 새로고침해야 다시 공개할 수 있었다(서버는 내린 뒤 재공개를
// 허용한다 — `backend/tests/test_classroom_problem_template.py` 가 보장한다).
//
// 화면이 판단할 것은 하나다: **가져갈 수 있는 템플릿이 지금 있는가.** 내려간 템플릿은
// 「있다」가 아니다. 그 판단을 여기 한 곳에 두고, 「방금 내렸다」는 안내는 화면이 따로
// 들고 있는다 — 서버에서 다시 받아온 값이 그 안내를 지우지 않게.
//
// 문제 템플릿과 클래스 템플릿이 같은 모양이라 같은 함수를 쓴다(#316·#319).

/** 화면이 실제로 쓰는 것은 공유 코드 하나다(#333 이 이 상태를 세운 이유). */
export type LiveTemplate = { shareCode: string } | null;

/**
 * 두 모양을 함께 받는다.
 *
 * - **공개·내리기 응답**은 `taken_down` 을 들고 온다 — 내린 직후에도 그 행을 돌려주므로
 *   이 칸이 참이면 살아 있는 것이 아니다.
 * - **상세 응답의 `published_template`** 에는 그 칸이 **없다** — 백엔드가 살아 있는
 *   것만 골라 싣고 아니면 `null` 이다(`_live_problem_template`). 그래서 칸이 없으면
 *   「살아 있다」로 읽는다.
 */
type TemplateResponse = { share_code: string; taken_down?: boolean };

/**
 * 공개·내리기 응답(또는 상세 응답의 `published_template`)에서 살아 있는 템플릿을 읽는다.
 *
 * `null` 이면 그 문제·클래스에는 지금 가져갈 수 있는 템플릿이 없다 — 공개 폼이 떠야 한다.
 */
export function liveTemplateFrom(template: TemplateResponse | null | undefined): LiveTemplate {
  if (!template) return null;
  if (template.taken_down === true) return null;
  return { shareCode: template.share_code };
}
