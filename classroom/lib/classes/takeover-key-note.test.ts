import { describe, expect, it } from "vitest";

import { decideKeyNote, type KeyNoteSnapshot } from "./takeover-key-note";

const snap = (over: Partial<KeyNoteSnapshot> = {}): KeyNoteSnapshot => ({ noteShown: true, connected: false, pendingTransferId: null, ...over });

// 화면이 하는 대로: 조회마다 decide, 알 수 없는(null) 동안은 마지막으로 안 연결 값을 이전 스냅샷에 둔다.
function run(steps: { now: Partial<KeyNoteSnapshot>; doneVisible?: boolean }[], start: KeyNoteSnapshot = snap()) {
  let prev = start;
  let doneVisible = false;
  const log: { complete: boolean; clearDone: boolean }[] = [];
  for (const step of steps) {
    doneVisible = step.doneVisible ?? doneVisible;
    const now = { ...prev, ...step.now };
    const action = decideKeyNote(prev, now, doneVisible);
    log.push(action);
    if (action.clearDone) doneVisible = false;
    if (action.complete) doneVisible = true;
    prev = { ...now, connected: now.connected ?? prev.connected, noteShown: action.complete ? false : now.noteShown };
  }
  return log;
}

describe("decideKeyNote", () => {
  it("키 없음 → 연결됨: 안내를 걷고 완료를 알린다", () => {
    expect(run([{ now: { connected: true } }])[0]).toEqual({ complete: true, clearDone: false });
  });
  it("키 없음이 이어지면 아무 일도 없다", () => {
    expect(run([{ now: { connected: false } }, { now: { connected: false } }]).every((a) => !a.complete && !a.clearDone)).toBe(true);
  });
  it("오류(null) 뒤 연결됨 회복: 안내가 걷히고 완료를 알린다 (#1535 ①)", () => {
    const log = run([{ now: { connected: false } }, { now: { connected: null } }, { now: { connected: true } }]);
    expect(log.map((a) => a.complete)).toEqual([false, false, true]);
  });
  it("처음 본 값이 오류 뒤 회복이어도 걷힌다", () => {
    const log = run([{ now: { connected: null } }, { now: { connected: true } }], snap({ connected: null }));
    expect(log.map((a) => a.complete)).toEqual([false, true]);
  });
  it("오류 동안은 완료 status 도 비우지 않는다", () => {
    expect(run([{ now: { connected: null, noteShown: false }, doneVisible: true }], snap({ noteShown: false, connected: true }))[0]).toEqual({ complete: false, clearDone: false });
  });
  it("완료 뒤 연결 해제(다른 탭에서 키 지움): 완료 status 를 비운다 (#1535 ③)", () => {
    const log = run([{ now: { connected: true } }, { now: { connected: false, noteShown: false } }]);
    expect(log[1]).toEqual({ complete: false, clearDone: true });
  });
  it("완료 뒤 새 이전 요청: 완료 status 를 비운다", () => {
    const log = run([{ now: { connected: true } }, { now: { noteShown: false, connected: true, pendingTransferId: 7 } }]);
    expect(log[1].clearDone).toBe(true);
  });
  it("연달은 두 사건(사이 조회 없이): 이전 요청 번호가 바뀌고 동시에 끊겨도 한 번 비운다", () => {
    const log = run(
      [{ now: { connected: true } }, { now: { noteShown: false, connected: false, pendingTransferId: 8 } }],
      snap({ pendingTransferId: 7 }),
    );
    expect(log[1]).toEqual({ complete: false, clearDone: true });
  });
  it("넘겼다 다시 받아 같은 완료가 반복: 두 번째 넘겨받음에서 비우고 다시 완료를 알린다", () => {
    const log = run([
      { now: { connected: true } },
      { now: { noteShown: false, connected: false } },
      { now: { noteShown: true, connected: false } },
      { now: { connected: true } },
    ]);
    expect(log.map((a) => [a.complete, a.clearDone])).toEqual([
      [true, false],
      [false, true],
      [false, false],
      [true, false],
    ]);
  });
  it("넘겨받음과 연결됨이 같은 조회로 오면 비운 뒤 다시 채운다", () => {
    const log = run([{ now: { noteShown: true, connected: true }, doneVisible: true }], snap({ noteShown: false, connected: true }));
    expect(log[0]).toEqual({ complete: true, clearDone: true });
  });
  it("완료가 떠 있는데 연결이 그대로면 비우지 않는다", () => {
    expect(run([{ now: { noteShown: false, connected: true }, doneVisible: true }], snap({ noteShown: false, connected: true }))[0].clearDone).toBe(false);
  });
});
