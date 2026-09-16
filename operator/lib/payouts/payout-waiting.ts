// 지급 큐의 대기 문구 — 순수 함수(#422, ADR-0020). 「무엇을 기다리나」(중립
// 배지)와 「누구 차례」(글자)를 분리한 것이 이 티켓의 핵심 변화다 — 예전에는
// 한 배지 문구가 둘을 뭉쳐 말했다. 셋 다 실패가 아니므로 색으로 겁주지 않고
// 글자로만 가른다(spec #421 user story 13/14/15/17).
export type BlockedOnKind = "identity" | "seller" | "transfer";

/** 「무엇을 기다리나」— 중립 배지에 넣는 짧은 이름. 셋이 서로 달라야 한다. */
export const WAITING_BADGE_LABEL: Record<BlockedOnKind, string> = {
  identity: "신원 대기",
  seller: "셀러 대기",
  transfer: "이체 대기",
};

export function waitingBadgeLabel(blockedOn: string): string {
  return WAITING_BADGE_LABEL[blockedOn as BlockedOnKind] ?? blockedOn;
}

/**
 * 「누구 차례」— 색이 아니라 글자로 가른다. `operatorActionable`(서버 판정,
 * `payouts.progress`)이 참이면 무엇을 기다리든 운영자 차례다 — 이미 진행
 * 버튼이 뜨는 조합과 같은 판정을 재사용한다. 정의되지 않은 `blocked_on`
 * 조합도 운영자 차례로 본다(시안 `Payouts.dc.html`의 「정의되지 않은 조합은
 * 운영자 차례다 — 돈은 움직이지 않고 사람이 본다」).
 */
export function whoseTurn(
  blockedOn: string,
  sellerRegistrationStatus: string | null,
  operatorActionable: boolean,
): string {
  if (operatorActionable) return "운영자 차례 — 재시도할 수 있습니다";
  switch (blockedOn) {
    case "identity":
      return "개발자 차례 — 세무 신원 확인 대기 중입니다";
    case "seller":
      return sellerRegistrationStatus === "stuck"
        ? "운영자 차례 — 자동 재시도가 실패했습니다"
        : "지급대행사 차례 — 등록 심사 중입니다";
    case "transfer":
      return "운영자 차례 — 실이체 재시도가 필요합니다";
    default:
      return "운영자 차례 — 정의되지 않은 대기입니다";
  }
}

/** 밀린 지 며칠째인가(user story 16) — 오늘 생긴 것은 "오늘"로 특별히 말한다. */
export function daysWaitingLabel(createdAt: string, now: Date = new Date()): string {
  const createdMs = new Date(createdAt).getTime();
  const days = Math.floor((now.getTime() - createdMs) / (24 * 60 * 60 * 1000));
  return days <= 0 ? "오늘" : `${days}일째`;
}
