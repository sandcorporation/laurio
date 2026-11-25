// 넘겨받은 안내(「채점 키 넣기」)와 완료 status(「채점 키를 넣었습니다」)를 언제 걷고·채우고·비우는가 (#1535 ①③).
// 화면은 조회 결과마다 이전 스냅샷과 지금 스냅샷을 이 함수에 넘기고, 돌려받은 할 일만 한다.
// `connected` 가 null 이면 모르는 것이다(불러오는 중·오류) — 그 동안은 아무것도 바꾸지 않고, 호출부는 마지막으로 안 값을 이전 스냅샷에 둔다.

export type KeyNoteSnapshot = {
  /** 넘겨받음 안내가 떠 있다(내가 소유자이고 방금 넘겨받았다). */
  noteShown: boolean;
  /** 채점 연결이 「연결됨」인가. null = 알 수 없음. */
  connected: boolean | null;
  /** 걸려 있는 소유권 이전 요청 번호. */
  pendingTransferId: number | null;
};

export type KeyNoteAction = {
  /** 넘겨받음 안내를 걷고 완료를 알린다(초점이 안내 안에 있었으면 먼저 옮긴다). */
  complete: boolean;
  /** 이미 읽힌 완료 status 를 비운다 — 완료가 이어지면 비운 뒤 다음 프레임에 다시 쓴다. */
  clearDone: boolean;
};

export function decideKeyNote(prev: KeyNoteSnapshot, now: KeyNoteSnapshot, doneVisible: boolean): KeyNoteAction {
  // 모르는 동안은 기준도 안내도 완료도 건드리지 않는다.
  if (now.connected === null) return { complete: false, clearDone: false };
  const complete = now.noteShown && now.connected;
  const newTransfer = now.pendingTransferId !== null && now.pendingTransferId !== prev.pendingTransferId;
  const disconnected = prev.connected === true && now.connected === false;
  const newTakeover = !prev.noteShown && now.noteShown;
  return { complete, clearDone: doneVisible && (newTransfer || disconnected || newTakeover) };
}
