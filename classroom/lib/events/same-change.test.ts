import { describe, expect, it } from "vitest";

import { SameChangeReads, changeRev } from "./same-change";

const instructors = (classId: number, rev?: number) => ({
  kind: "instructors-changed",
  payload: rev === undefined ? { class_id: classId } : { class_id: classId, rev },
});
const participation = (classId: number, rev?: number) => ({
  kind: "participation-changed",
  payload: rev === undefined ? { class_id: classId } : { class_id: classId, rev },
});

describe("changeRev", () => {
  it("본문의 변경 번호를 읽고, 없거나 숫자가 아니면 모른다", () => {
    expect(changeRev({ class_id: 1, rev: 7 })).toBe(7);
    expect(changeRev({ class_id: 1 })).toBeNull();
    expect(changeRev({ class_id: 1, rev: "7" })).toBeNull();
  });
});

// 훅이 하는 대로 돌린다 — 신호가 참이면 읽기를 보내고, 조회의 끝(성공·실패)을 넘긴다. 보낸 읽기 수를 센다.
function driver() {
  const reads = new SameChangeReads();
  let sent = 0;
  const send = (go: boolean) => {
    if (go) sent += 1;
  };
  return {
    signal: (event: { kind: string; payload: Record<string, unknown> }) => send(reads.signal(event)),
    ok: () => send(reads.settled(true)),
    fail: () => send(reads.settled(false)),
    get sent() {
      return sent;
    },
  };
}

describe("SameChangeReads — 같은 변경의 두 신호 (#1496 ⑤)", () => {
  it("같은 변경 번호의 두 번째 신호는 종류가 달라도, 어느 쪽이 먼저 와도 읽은 변경이다", () => {
    const participationFirst = driver();
    participationFirst.signal(participation(1, 5));
    participationFirst.ok();
    participationFirst.signal(instructors(1, 5));
    expect(participationFirst.sent).toBe(1);

    const instructorsFirst = driver();
    instructorsFirst.signal(instructors(1, 5));
    instructorsFirst.signal(participation(1, 5));
    instructorsFirst.ok();
    expect(instructorsFirst.sent).toBe(1);
  });

  it("더 큰 번호는 새 변경이고, 늦게 닿은 작은 번호는 큰 번호의 재조회가 이미 담는다", () => {
    const d = driver();
    d.signal(instructors(1, 5));
    d.ok();
    d.signal(instructors(1, 6));
    d.ok();
    d.signal(participation(1, 5));
    expect(d.sent).toBe(2);
  });

  it("클래스마다 따로 센다", () => {
    const d = driver();
    d.signal(instructors(1, 5));
    d.signal(instructors(2, 5));
    expect(d.sent).toBe(2);
  });
});

describe("SameChangeReads — 첫 조회가 실패하면 (#1503 ③)", () => {
  it("실패 사이: 첫 조회가 실패한 뒤 온 같은 번호의 신호가 다시 읽고, 성공하면 그 번호를 읽은 것으로 친다", () => {
    const d = driver();
    d.signal(participation(1, 5));
    d.fail();
    expect(d.sent).toBe(1);
    d.signal(instructors(1, 5));
    expect(d.sent).toBe(2);
    d.ok();
    d.signal(participation(1, 5));
    expect(d.sent).toBe(2);
  });

  it("신호 먼저: 조회가 도는 사이 건너뛴 같은 번호의 신호는 그 조회가 실패하면 한 번 더 읽는다", () => {
    const d = driver();
    d.signal(participation(1, 5));
    d.signal(instructors(1, 5));
    expect(d.sent).toBe(1);
    d.fail();
    expect(d.sent).toBe(2);
    d.ok();
    d.signal(participation(1, 5));
    expect(d.sent).toBe(2);
  });

  it("그 한 번 더도 실패하면 멈추고, 다음 같은 번호의 신호가 다시 읽는다", () => {
    const d = driver();
    d.signal(participation(1, 5));
    d.signal(instructors(1, 5));
    d.fail();
    d.fail();
    expect(d.sent).toBe(2);
    d.signal(instructors(1, 5));
    expect(d.sent).toBe(3);
  });

  it("건너뛴 신호가 없으면 실패 뒤 스스로 다시 읽지 않는다", () => {
    const d = driver();
    d.signal(participation(1, 5));
    d.fail();
    expect(d.sent).toBe(1);
  });

  it("응답 먼저: 성공한 뒤 온 같은 번호의 신호는 읽지 않는다", () => {
    const d = driver();
    d.signal(participation(1, 5));
    d.ok();
    d.signal(instructors(1, 5));
    expect(d.sent).toBe(1);
  });
});

describe("SameChangeReads — 번호 없는 신호(옛 서버)", () => {
  it("신호 하나에 조회 하나 — 두 신호면 둘, 실패해도 스스로 더 읽지 않는다", () => {
    const d = driver();
    d.signal(instructors(1));
    d.signal(participation(1));
    expect(d.sent).toBe(2);
    d.fail();
    expect(d.sent).toBe(2);

    const settledBetween = driver();
    settledBetween.signal(instructors(1));
    settledBetween.fail();
    settledBetween.signal(participation(1));
    settledBetween.ok();
    expect(settledBetween.sent).toBe(2);
  });
});
