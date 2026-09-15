// 무료 공모전 목록의 「운영팀 알림 보내기」가 실어 보낸 쿼리를 받는 사람으로
// 되돌린다(#420) — 짝은 `lib/free-contests/notify-link.ts`. `display_name`
// 판정은 백엔드 `notifications/operator_api.py`의 `_display_name`과 같은
// 순서다(닉네임 → 이메일 → 계정 번호).
import type { Recipient } from "./types";

export function recipientFromSearchParams(
  searchParams: URLSearchParams,
): Recipient | null {
  const idRaw = searchParams.get("recipient_id");
  const email = searchParams.get("recipient_email");
  if (idRaw === null || email === null) return null;

  const id = Number(idRaw);
  if (!Number.isInteger(id)) return null;

  const nickname = searchParams.get("recipient_nickname") ?? "";
  const displayName = nickname || email || `계정 #${id}`;

  return { id, email, display_name: displayName };
}
