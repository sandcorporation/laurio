// 브라우저가 이미 떠난 요청의 실패를 오류로 올리지 않는다(2026-09-21, GlitchTip 65).
//
// `forward.ts` 는 브라우저가 끊으면 위쪽 요청도 끊도록 요청 신호를 넘긴다. 그
// 신호가 위쪽 **응답 헤더가 오기 전에** 끊기면 `fetch` 가 신호의 사유 —
// Next 가 넣는 `ResponseAborted` — 로 거절하고, 그대로 두면 라우트가 던져
// Next 의 `onRequestError` 가 오류로 보고한다. 배포 직후가 그 모양이다: 새
// 컨테이너로 다시 붙은 EventSource 가 이벤트 서비스의 첫 응답을 기다리는 사이
// 탭이 닫히거나 다시 끊긴다(오류 65 는 강의실 컨테이너가 뜬 지 1.3초 뒤였다).
// 받을 사람이 없는 응답이라 고칠 것도 알릴 것도 없다 — 이미 떠난 스트림이
// 중간에 끊기는 것을 조용히 닫는 `event-stream.ts` 와 같은 판단이다.
//
// **판정은 예외 모양이 아니라 신호다.** 브라우저가 남아 있는 동안의 실패(연결
// 거부 재시도가 다 떨어진 것 등)는 그대로 던진다 — 그건 우리 쪽 사고다.

export async function unlessClientLeft<T>(
  signal: AbortSignal,
  work: () => Promise<T>,
): Promise<T | null> {
  try {
    return await work();
  } catch (error) {
    if (signal.aborted) return null;
    throw error;
  }
}
