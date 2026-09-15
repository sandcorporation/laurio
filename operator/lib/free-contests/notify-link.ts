// 수상자 옆 「운영팀 알림 보내기」가 여는 주소(#420) — 작성 화면(`/notifications`)이
// 받는 사람을 검색하지 않고 바로 채워서 열리도록 쿼리에 싣는다. 화면 쪽 파싱은
// `lib/notifications/recipient-from-query.ts`가 짝으로 한다.
import type { FreeContestWinner } from "./types";

export function operatorNoticeComposeHref(winner: FreeContestWinner): string {
  const params = new URLSearchParams({
    recipient_id: String(winner.user_id),
    recipient_email: winner.email,
    recipient_nickname: winner.nickname,
  });
  return `/notifications?${params.toString()}`;
}
