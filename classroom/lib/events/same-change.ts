// 같은 변경이 신호 둘로 오는 것을 번호로 알아본다 (#1496 ⑤). 백엔드는 클래스 쪽 변경마다 변경 번호(`rev`)를 하나 올려
// `instructors-changed`·`participation-changed` 에 같은 값으로 싣는다 — 참여자 행이 있는 강사는 보관·문제 쓰기 한 번에
// 둘을 함께 받는다. 시간 창(예전 250ms)은 두 신호가 그보다 벌어지면 두 번 읽었다. 번호는 벌어진 시간과 상관없다.
//
// 번호는 **성공한 조회**까지만 읽은 것으로 친다 (#1503 ③). 예전에는 신호를 받는 순간 번호를 기억해, 첫 조회가 실패하면
// 같은 번호의 두 번째 신호도 버렸다 — 스트림이 붙어 있으면 폴링도 없어 다음 변경까지 오류 화면에 머물렀다.

import type { StreamEvent } from "./types";

/** 신호 본문의 클래스 변경 번호 — 없거나 숫자가 아니면 모른다(null, 옛 서버). */
export function changeRev(payload: Record<string, unknown>): number | null {
  const rev = payload.rev;
  return typeof rev === "number" && Number.isFinite(rev) ? rev : null;
}

function raise(map: Map<number, number>, classId: number, rev: number) {
  const last = map.get(classId);
  if (last === undefined || rev > last) map.set(classId, rev);
}

function covers(map: Map<number, number>, classId: number, rev: number) {
  const last = map.get(classId);
  return last !== undefined && rev <= last;
}

/** 화면 하나의 재조회가 어느 변경 번호까지 읽었는지 든다(화면 하나에 하나). 번호는 클래스 행의 잠금 아래 하나씩 오르고
 * 신호는 커밋 뒤에 나가므로, 더 큰 번호를 담은 조회가 작은 번호의 변경을 이미 담는다. 번호 없는 신호(옛 서버·채점
 * 신호)는 늘 읽는다 — 모르는 것은 읽되, 신호 하나에 조회 하나다(실패해도 스스로 되풀이하지 않는다). */
export class SameChangeReads {
  /** 성공한 조회가 담은 번호(클래스마다). */
  private readonly read = new Map<number, number>();
  /** 지금 도는 조회가 담을 번호(클래스마다) — 성공하면 `read` 로 옮기고, 실패하면 버린다. */
  private readonly reading = new Map<number, number>();
  /** 도는 조회가 담을 번호라 건너뛴 신호가 있다 — 그 조회가 실패하면 그 신호 몫으로 한 번 더 읽는다. */
  private skippedWhileReading = false;

  /** 신호 하나를 받았다 — 다시 읽어야 하면 참. */
  signal(event: StreamEvent): boolean {
    const classId = event.payload.class_id;
    const rev = changeRev(event.payload);
    if (typeof classId !== "number" || rev === null) return true;
    if (covers(this.read, classId, rev)) return false;
    if (covers(this.reading, classId, rev)) {
      this.skippedWhileReading = true;
      return false;
    }
    raise(this.reading, classId, rev);
    return true;
  }

  /** 조회 하나가 끝났다(어느 길로 부른 조회든 — 새 조회는 앞 조회를 버리므로 끝나는 것은 늘 마지막 조회다).
   * 실패했고 그 사이 같은 변경의 신호를 건너뛰었으면 참 — 그 신호 몫으로 한 번 더 읽는다. */
  settled(ok: boolean): boolean {
    if (ok) {
      for (const [classId, rev] of this.reading) raise(this.read, classId, rev);
      this.reading.clear();
      this.skippedWhileReading = false;
      return false;
    }
    if (this.skippedWhileReading) {
      // 다시 읽는 조회가 같은 번호를 담는다 — `reading` 을 그대로 둔다.
      this.skippedWhileReading = false;
      return true;
    }
    this.reading.clear();
    return false;
  }
}
