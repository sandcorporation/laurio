import type { PendingOwnershipTransfer } from "@/lib/classes/api";

/**
 * 소유자가 보낸 이전 요청이 끝났을 때 강사 탭이 읽어 줄 한 줄(#1448 ③). 거절·만료·받는 사람이 떠남은 클래스
 * 응답만으로 가르지 않는다 — 알림 값에 기대지 않고 「끝났고 소유자는 그대로」만 말한다. 역할이 바뀐 끝(넘겨줌)은
 * 클래스 화면의 「넘겨받았습니다」 안내가 맡으므로 여기서는 `null`.
 */
export function pendingTransferEndNote({
  ended,
  now,
  stillOwner,
  cancelledByMe,
}: {
  ended: PendingOwnershipTransfer | null;
  now: PendingOwnershipTransfer | null;
  stillOwner: boolean;
  cancelledByMe: boolean;
}): string | null {
  if (ended === null || now !== null || !stillOwner) return null;
  if (cancelledByMe) return "소유권 이전 요청을 취소했습니다.";
  const name = ended.recipient_display_name || "받는 사람";
  return `${name}님에게 보낸 소유권 이전 요청이 끝났습니다. 소유자는 그대로입니다.`;
}

/**
 * 나에게 온 이전 요청이 내가 답하기 전에 끝났을 때(소유자의 취소·만료) 클래스 화면이 읽어 줄 한 줄. 취소와 만료는
 * 클래스 응답만으로 가르지 않는다.
 */
export function offerEndNote(ownerName: string): string {
  const owner = ownerName ? `${ownerName}님이` : "소유자가";
  return `${owner} 보낸 소유권 이전 요청이 끝났습니다. 공동 강사로 남습니다.`;
}

/**
 * 나에게 온 이전 요청이 클래스 화면에 나타났을 때(열어 둔 채 신호로 오거나 처음 열 때) 읽어 줄 한 줄(#1490).
 * 보내는 쪽의 「답을 기다립니다」와 다른 사람의 말이라 받는 사람 기준으로 따로 쓴다.
 */
export function offerArrivedNote(ownerName: string): string {
  const owner = ownerName ? `${ownerName}님이` : "소유자가";
  return `${owner} 소유권을 넘기려 합니다 — 받기 또는 거절할 수 있습니다.`;
}

/** 강사 표의 대기 요청 줄 — 보는 사람에 따라 말이 다르다. `day` 는 이미 쓰인 날짜 표기. */
export function pendingTransferRowText(transfer: PendingOwnershipTransfer, day: string): string {
  if (transfer.recipient_is_me) return `나에게 온 요청 · ${day} 까지 답할 수 있습니다`;
  return `${day} 까지 답을 기다립니다`;
}
