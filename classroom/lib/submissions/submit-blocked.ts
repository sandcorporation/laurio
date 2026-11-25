/**
 * 제출이 403 으로 거절되면 화면이 낡았다는 뜻이다(보관·내보냄·숨김) — 새로 고친 뒤와 같은 상태로
 * 넘어가려면 문제 정보를 다시 읽어야 한다(#1422). 시도가 없는 참여자에게는 숨긴 문제가 존재를 숨겨
 * 404 로 거절된다(#1431) — 그 뒤 다시 읽으면 찾을 수 없음 안내가 된다. 백엔드 계약은 그대로, 상태 코드만 본다.
 */
export function submitRejectedAsBlocked(result: { ok: boolean; status?: number }): boolean {
  return !result.ok && (result.status === 403 || result.status === 404);
}
