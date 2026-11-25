import { describe, expect, it } from "vitest";

import { ClassSignalReload, signalRev } from "./signal-rev";

// 훅이 하는 대로 돌린다 — 참이 나오면 읽기를 보내고(`started`), 응답·실패를 받는다. 보낸 읽기 수를 센다.
function driver() {
  const machine = new ClassSignalReload();
  let reads = 0;
  const start = (go: boolean) => {
    if (!go) return;
    machine.started();
    reads += 1;
  };
  return {
    machine,
    signal: (rev: number | null) => start(machine.signal(rev)),
    respond: (rev: number | null) => start(machine.succeeded(rev)),
    fail: () => machine.failed(),
    get reads() {
      return reads;
    },
  };
}

describe("signalRev", () => {
  it("본문의 변경 번호를 읽고, 없거나 숫자가 아니면 모른다", () => {
    expect(signalRev({ class_id: 1, rev: 7 })).toBe(7);
    expect(signalRev({ class_id: 1 })).toBeNull();
    expect(signalRev({ class_id: 1, rev: "7" })).toBeNull();
  });
});

describe("ClassSignalReload — 번호", () => {
  it("이미 읽은 번호 이하의 신호는 읽지 않는다", () => {
    const d = driver();
    d.respond(5);
    d.signal(5);
    d.signal(4);
    expect(d.reads).toBe(0);
  });

  it("읽은 번호보다 큰 신호는 한 번 읽고, 그 번호를 담은 응답에서 멈춘다", () => {
    const d = driver();
    d.respond(5);
    d.signal(6);
    d.respond(6);
    expect(d.reads).toBe(1);
  });

  it("읽는 중에 온 더 큰 번호는 응답이 온 뒤 한 번 더 읽는다(신호 먼저 → 응답)", () => {
    const d = driver();
    d.signal(1);
    d.signal(2);
    expect(d.reads).toBe(1);
    d.respond(1);
    expect(d.reads).toBe(2);
    d.respond(2);
    expect(d.reads).toBe(2);
  });

  it("응답이 이미 그 번호를 담았으면 늦게 온 신호는 읽지 않는다(응답 먼저 → 신호)", () => {
    const d = driver();
    d.signal(1);
    d.respond(2);
    d.signal(2);
    expect(d.reads).toBe(1);
  });
});

describe("ClassSignalReload — 번호 없는 신호·응답 (#1496 ③)", () => {
  it("번호 없는 신호 하나에 번호 없는 응답 — 정확히 한 번 읽는다", () => {
    const d = driver();
    d.respond(null);
    d.signal(null);
    d.respond(null);
    d.respond(null);
    expect(d.reads).toBe(1);
  });

  it("번호 있는 신호에 번호 없는 응답 — 정확히 한 번 읽는다", () => {
    const d = driver();
    d.respond(null);
    d.signal(3);
    d.respond(null);
    expect(d.reads).toBe(1);
  });

  it("번호 없는 신호에 번호 있는 응답 — 정확히 한 번 읽는다", () => {
    const d = driver();
    d.respond(4);
    d.signal(null);
    d.respond(5);
    expect(d.reads).toBe(1);
  });

  it("읽는 중에 온 번호 없는 신호는 응답 뒤 한 번만 더 읽는다", () => {
    const d = driver();
    d.signal(null);
    d.signal(null);
    d.signal(null);
    expect(d.reads).toBe(1);
    d.respond(null);
    expect(d.reads).toBe(2);
    d.respond(null);
    expect(d.reads).toBe(2);
  });

  it("번호 없는 응답 뒤 읽는 사이 온 번호 있는 신호는 한 번 더 읽는다", () => {
    const d = driver();
    d.signal(1);
    d.signal(2);
    d.respond(null);
    expect(d.reads).toBe(2);
    d.respond(null);
    expect(d.reads).toBe(2);
  });
});

describe("ClassSignalReload — 실패 (#1496 ④)", () => {
  it("실패하면 읽는 중이 풀려 다음 신호가 다시 읽는다 — 잇단 실패 뒤에도", () => {
    const d = driver();
    d.signal(1);
    d.fail();
    expect(d.machine.reading).toBe(false);
    d.signal(2);
    d.fail();
    d.signal(3);
    expect(d.reads).toBe(3);
    d.respond(3);
    expect(d.reads).toBe(3);
  });

  it("실패한 뒤 스스로 곧바로 다시 읽지 않는다 — 실패를 되풀이해 두드리지 않는다", () => {
    const d = driver();
    d.signal(1);
    d.fail();
    expect(d.reads).toBe(1);
    expect(d.machine.due()).toBe(true);
  });

  it("실패 사이에 온 번호 없는 신호도 다음 기회에 읽는다", () => {
    const d = driver();
    d.signal(1);
    d.signal(null);
    d.fail();
    d.signal(null);
    expect(d.reads).toBe(2);
  });
});

describe("ClassSignalReload — 내 명령", () => {
  it("명령이 도는 사이 읽기를 부른 신호가 왔을 때만 참이다", () => {
    const d = driver();
    d.respond(7);
    const quiet = d.machine.commandMark();
    d.signal(7);
    expect(d.machine.signalSince(quiet)).toBe(false);
    const busy = d.machine.commandMark();
    d.signal(8);
    expect(d.machine.signalSince(busy)).toBe(true);
    const unnumbered = d.machine.commandMark();
    d.signal(null);
    expect(d.machine.signalSince(unnumbered)).toBe(true);
  });
});
