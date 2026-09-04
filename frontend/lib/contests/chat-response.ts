// AI grill 대화 응답을 신뢰할 수 없는 입력으로 다룬다 (#37 FE-12 인수조건 —
// "LLM이 이상하거나 형식에 맞지 않는 응답을 해도 화면이 죽지 않는다. 모델의
// 예상 밖 응답은 정상 운영 조건이다").
//
// 백엔드(contests/requirement_chat.py `send_requirement_chat_message`)는 어댑터
// 실패를 이미 사과 응답으로 감성하고, django-ninja의 `response=` 스키마가 응답
// 형태를 강제한다 — 그래서 "지금 배포된 백엔드가 정상"이라면 이 함수가 실제로
// 걸러낼 것은 거의 없다. 하지만 그 보장은 이 화면이 통제할 수 없는 두 층에서
// 깨질 수 있다: ① BFF 프록시가 502/504를 빈 본문으로 삼키거나 HTML 에러 페이지를
// 대신 돌려줄 때, ② 백엔드가 회귀해 스키마 자체가 깨질 때. 어느 쪽이든 이 화면이
// `res.json() as RequirementChatResponseOut`처럼 타입 캐스팅만 믿으면 그 순간
// 런타임 예외로 화면이 죽는다. 그래서 필드 하나하나를 직접 검증해 안전한 값으로
// 정규화하고, 검증되지 않은 조각은 조용히 버린다 — 절대 예외를 던지지 않는다.
export type ChatProposal = { text: string; grade: "required" | "optional" };
export type ParsedChatReply = { reply: string; proposals: ChatProposal[] };
export type ParsedChatTurn = { role: string; content: string; created_at: string };

// contests/schemas.py RequirementIn.text: Field(max_length=500)과 같다.
const MAX_PROPOSAL_TEXT_LENGTH = 500;
// 채팅 말풍선이 무한정 길어져 레이아웃을 무너뜨리는 것을 막는 표시 상한 —
// "터무니없이 긴 문자열"에 대한 방어선이다. 백엔드 계약에 없는 값이라 넉넉하게
// 잡는다.
const MAX_REPLY_DISPLAY_LENGTH = 4000;
// contests/requirement_chat.py `_MAX_PROPOSALS_PER_TURN`과 같다 — 한 턴에서 화면에
// 그려질 제안 개수를 같은 상한으로 맞춘다.
const MAX_PROPOSALS_PER_TURN = 5;

export const FALLBACK_CHAT_REPLY =
  "AI 응답을 해석하지 못했어요 — 다른 방식으로 다시 말씀해 주시겠어요?";

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * `raw`는 무엇이든 될 수 있다고 가정한다 — JSON이 아예 아닌 원시값(문자열·숫자·
 * null 등 `JSON.parse`가 그대로 통과시키는 값), 필드가 빠진 객체, 필드 타입이
 * 다른 객체, `proposed_requirements`가 배열이 아니거나 빈 배열인 경우 전부.
 * 유효하지 않은 조각은 걸러내고, 무엇을 받든 항상 렌더링 가능한 값을 돌려준다.
 */
export function parseChatReply(raw: unknown): ParsedChatReply {
  const obj = isPlainObject(raw) ? raw : {};

  const reply =
    typeof obj.reply === "string" && obj.reply.trim().length > 0
      ? obj.reply.slice(0, MAX_REPLY_DISPLAY_LENGTH)
      : FALLBACK_CHAT_REPLY;

  const rawProposals = Array.isArray(obj.proposed_requirements) ? obj.proposed_requirements : [];

  const proposals: ChatProposal[] = [];
  for (const candidate of rawProposals) {
    if (proposals.length >= MAX_PROPOSALS_PER_TURN) break;
    if (!isPlainObject(candidate)) continue;
    const text =
      typeof candidate.text === "string"
        ? candidate.text.trim().slice(0, MAX_PROPOSAL_TEXT_LENGTH)
        : "";
    if (!text) continue;
    // 등급이 빠졌거나 "required"/"optional"이 아닌 값이면 더 무거운 쪽(필수)을
    // 기본값으로 삼는다 — 이 항목이 실제 체크리스트가 되면 자가 응답·심사·채점의
    // 기준이 되므로(REQUEST.md), 모호한 등급을 조용히 "선택"으로 낮춰 분쟁
    // 예방이라는 이 화면의 목적을 스스로 배신하지 않는다.
    const grade: ChatProposal["grade"] = candidate.grade === "optional" ? "optional" : "required";
    proposals.push({ text, grade });
  }

  return { reply, proposals };
}

/**
 * 대화 이력 배열(`messages`)도 같은 이유로 방어적으로 다룬다 — 항목 하나가
 * 깨져 있다고 전체 이력을 비워버리지 않는다.
 */
export function sanitizeChatTurns(raw: unknown): ParsedChatTurn[] {
  if (!Array.isArray(raw)) return [];
  const turns: ParsedChatTurn[] = [];
  for (const item of raw) {
    if (!isPlainObject(item)) continue;
    const role = item.role === "assistant" || item.role === "sponsor" ? item.role : null;
    const content = typeof item.content === "string" ? item.content : "";
    if (!role || !content.trim()) continue;
    const createdAt = typeof item.created_at === "string" ? item.created_at : new Date().toISOString();
    turns.push({ role, content: content.slice(0, MAX_REPLY_DISPLAY_LENGTH), created_at: createdAt });
  }
  return turns;
}
