import { describe, expect, it } from "vitest";

import { decideStreamRefresh } from "./policy";

describe("decideStreamRefresh", () => {
  it("연결됨: 기다리는 중이어도 폴링하지 않는다", () => {
    const decision = decideStreamRefresh("open", "open", true, 4_000);
    expect(decision.pollIntervalMs).toBeNull();
    expect(decision.refetchNow).toBe(false);
  });

  it("끊김 + 기다리는 중: 호출부가 준 간격으로 폴링한다", () => {
    const decision = decideStreamRefresh("closed", "closed", true, 4_000);
    expect(decision.pollIntervalMs).toBe(4_000);
    expect(decision.refetchNow).toBe(false);
  });

  // #467 — 기다리는 중이 아니면(예: 「채점 중」 시도가 없다) 스트림이 끊겨도
  // 폴링하지 않는다. 예전에는 이 판단을 호출부(use-my-problem.ts 등)가
  // `if (!hasPendingAttempt) return`으로 직접 했다 — 순수 함수가 계약에
  // 없는 조건을 화면마다 다시 구현한 것이다. 이제 이 함수가 유일한 출처다.
  it("끊김 + 기다리는 중이 아님: 폴링하지 않는다", () => {
    const decision = decideStreamRefresh("closed", "closed", false, 4_000);
    expect(decision.pollIntervalMs).toBeNull();
    expect(decision.refetchNow).toBe(false);
  });

  it("연결 중 + 기다리는 중이 아님: 그래도 폴링하지 않는다", () => {
    const decision = decideStreamRefresh("connecting", "connecting", false, 30_000);
    expect(decision.pollIntervalMs).toBeNull();
  });

  it("연결 중 + 기다리는 중: 아직 열리지 않았으니 폴링으로 물러난다", () => {
    const decision = decideStreamRefresh("connecting", "connecting", true, 30_000);
    expect(decision.pollIntervalMs).toBe(30_000);
    expect(decision.refetchNow).toBe(false);
  });

  it("끊김 -> 연결됨: 기다리는 중이 아니어도 재조회는 한다 — 재조회는 waiting과 무관하다", () => {
    const decision = decideStreamRefresh("closed", "open", false, 4_000);
    expect(decision.pollIntervalMs).toBeNull();
    expect(decision.refetchNow).toBe(true);
  });

  it("연결 중 -> 연결됨(첫 연결)도 재조회로 취급한다", () => {
    const decision = decideStreamRefresh("connecting", "open", true, 4_000);
    expect(decision.refetchNow).toBe(true);
  });

  it("연결됨 -> 끊김 + 기다리는 중: 재조회 없이 폴링만 켠다", () => {
    const decision = decideStreamRefresh("open", "closed", true, 4_000);
    expect(decision.pollIntervalMs).toBe(4_000);
    expect(decision.refetchNow).toBe(false);
  });

  it("연결됨 -> 연결됨(변화 없음)은 재조회하지 않는다", () => {
    const decision = decideStreamRefresh("open", "open", true, 4_000);
    expect(decision.refetchNow).toBe(false);
  });

  it("호출부마다 다른 fallback 간격을 그대로 돌려준다 — 벨은 30초, 화면은 짧게", () => {
    expect(decideStreamRefresh("closed", "closed", true, 30_000).pollIntervalMs).toBe(30_000);
    expect(decideStreamRefresh("closed", "closed", true, 3_000).pollIntervalMs).toBe(3_000);
  });
});
