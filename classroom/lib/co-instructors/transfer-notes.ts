// 소유자가 넘기려던 소유권을 이미 상대가 넘겨받았을 때 소유자 화면에 한 번 보이는 한 줄(#1441 5번).
// 이름이 없으면 조사가 달라진다(님이 · 받는 사람이).

export function takenOverNoteText(newOwnerName: string, afterCancelAttempt: boolean): string {
  const who = newOwnerName ? `${newOwnerName}님이` : "받는 사람이";
  return afterCancelAttempt
    ? `이미 ${who} 넘겨받았습니다 — 요청은 취소되지 않았고, 이제 나는 이 클래스의 공동 강사입니다.`
    : `${who} 소유권을 넘겨받았습니다 — 이제 나는 이 클래스의 공동 강사입니다.`;
}
