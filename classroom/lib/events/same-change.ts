// 같은 변경이 신호 둘로 오는 것을 번호로 알아본다 (#1496 ⑤). 백엔드는 클래스 쪽 변경마다 변경 번호(`rev`)를 하나 올려
// `instructors-changed`·`participation-changed` 에 같은 값으로 싣는다 — 참여자 행이 있는 강사는 보관·문제 쓰기 한 번에
// 둘을 함께 받는다. 시간 창(예전 250ms)은 두 신호가 그보다 벌어지면 두 번 읽었다. 번호는 벌어진 시간과 상관없다.

import type { StreamEvent } from "./types";

/** 신호 본문의 클래스 변경 번호 — 없거나 숫자가 아니면 모른다(null, 옛 서버). */
export function changeRev(payload: Record<string, unknown>): number | null {
  const rev = payload.rev;
  return typeof rev === "number" && Number.isFinite(rev) ? rev : null;
}

/** 이미 읽은 변경의 신호인가를 가르는 기억 하나를 만든다(화면 하나에 하나). 클래스마다 본 가장 큰 번호를 들고, 그
 * 이하의 번호면 참이다 — 번호는 클래스 행의 잠금 아래 하나씩 오르고 신호는 커밋 뒤에 나가므로, 더 큰 번호의 재조회가
 * 작은 번호의 변경을 이미 담는다. 번호 없는 신호(옛 서버·채점 신호)는 늘 거짓이다 — 모르는 것은 읽는다. */
export function createSameChangeFilter(): (event: StreamEvent) => boolean {
  const seen = new Map<number, number>();
  return (event) => {
    const classId = event.payload.class_id;
    const rev = changeRev(event.payload);
    if (typeof classId !== "number" || rev === null) return false;
    const last = seen.get(classId);
    if (last !== undefined && rev <= last) return true;
    seen.set(classId, rev);
    return false;
  };
}
