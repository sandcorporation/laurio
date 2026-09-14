import { describe, expect, it } from "vitest";

import { decideStreamRefresh } from "./policy";

describe("decideStreamRefresh", () => {
  it("연결됨: 폴링하지 않는다", () => {
    const decision = decideStreamRefresh("open", "open", 4_000);
    expect(decision.pollIntervalMs).toBeNull();
    expect(decision.refetchNow).toBe(false);
  });

  it("끊김: 호출부가 준 간격으로 폴링한다", () => {
    const decision = decideStreamRefresh("closed", "closed", 4_000);
    expect(decision.pollIntervalMs).toBe(4_000);
    expect(decision.refetchNow).toBe(false);
  });

  it("연결 중: 아직 열리지 않았으니 폴링으로 물러난다", () => {
    const decision = decideStreamRefresh("connecting", "connecting", 30_000);
    expect(decision.pollIntervalMs).toBe(30_000);
    expect(decision.refetchNow).toBe(false);
  });

  it("끊김 -> 연결됨: 폴링을 멈추고 한 번 재조회한다", () => {
    const decision = decideStreamRefresh("closed", "open", 4_000);
    expect(decision.pollIntervalMs).toBeNull();
    expect(decision.refetchNow).toBe(true);
  });

  it("연결 중 -> 연결됨(첫 연결)도 재조회로 취급한다", () => {
    const decision = decideStreamRefresh("connecting", "open", 4_000);
    expect(decision.refetchNow).toBe(true);
  });

  it("연결됨 -> 끊김: 재조회 없이 폴링만 켠다", () => {
    const decision = decideStreamRefresh("open", "closed", 4_000);
    expect(decision.pollIntervalMs).toBe(4_000);
    expect(decision.refetchNow).toBe(false);
  });

  it("연결됨 -> 연결됨(변화 없음)은 재조회하지 않는다", () => {
    const decision = decideStreamRefresh("open", "open", 4_000);
    expect(decision.refetchNow).toBe(false);
  });

  it("호출부마다 다른 fallback 간격을 그대로 돌려준다 — 벨은 30초, 화면은 짧게", () => {
    expect(decideStreamRefresh("closed", "closed", 30_000).pollIntervalMs).toBe(30_000);
    expect(decideStreamRefresh("closed", "closed", 3_000).pollIntervalMs).toBe(3_000);
  });
});
