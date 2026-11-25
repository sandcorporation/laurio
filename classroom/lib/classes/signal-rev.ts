// 강사 쪽 변경 신호(`instructors-changed`)의 변경 번호 판단 (#1484 ④). 번호는 백엔드가 변경마다 하나 올려 신호 본문과
// 클래스 응답에 같은 값으로 싣는다 — 시간 창이 아니라 「이미 읽은 번호인가」로 같은 변경의 재조회를 하나로 모은다.

/** 신호 본문의 변경 번호 — 없거나 숫자가 아니면 모른다(null). */
export function signalRev(payload: Record<string, unknown>): number | null {
  const rev = payload.rev;
  return typeof rev === "number" && Number.isFinite(rev) ? rev : null;
}

/** 지금 클래스를 다시 읽어야 하는가 — 본 가장 큰 번호가 읽은 번호보다 크고, 읽는 중이 아닐 때만.
 * 읽는 중이면 응답이 와서 읽은 번호가 바뀐 뒤 다시 판단한다. */
export function shouldReloadForRev(seenRev: number, loadedRev: number, inFlight: boolean): boolean {
  return seenRev > loadedRev && !inFlight;
}

/** 내 명령이 끝났을 때 자체 재조회를 건너뛰는가 — 명령이 도는 사이 신호가 왔으면(내 변경의 것일 수 있다) 그 신호 길이
 * 번호를 비교해 읽는다. 신호가 아직 안 왔으면 자체 재조회가 읽고, 뒤따라 온 그 신호는 번호가 이미 읽은 값이라 건너뛴다. */
export function signalArrivedDuringCommand(seenRevNow: number, seenRevAtStart: number): boolean {
  return seenRevNow > seenRevAtStart;
}
