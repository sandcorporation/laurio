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
