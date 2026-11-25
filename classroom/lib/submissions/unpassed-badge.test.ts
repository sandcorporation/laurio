import { describe, expect, it } from "vitest";

import { unpassedBadge } from "./unpassed-badge";

const row = (attempt_number: number, status: "pending" | "scored", pending_reason: string | null = null) =>
  ({ attempt_number, status, pending_reason }) as Parameters<typeof unpassedBadge>[0][number];

describe("unpassedBadge", () => {
  it("한 번도 안 냈으면 목록과 같은 「미제출」", () => {
    expect(unpassedBadge([])).toEqual({ label: "미제출", tone: "neutral" });
  });

  it("판정된 시도로 통과하지 못했으면 「미통과」", () => {
    expect(unpassedBadge([row(1, "scored"), row(2, "scored")])).toEqual({ label: "미통과", tone: "error" });
  });

  it("마지막 시도가 키·모델 사정으로 멈췄으면 목록과 같은 「채점 대기」(중립)", () => {
    expect(unpassedBadge([row(1, "pending", "no_key")])).toEqual({ label: "채점 대기", tone: "neutral" });
  });

  it("마지막 시도가 채점 중이면 「채점 중」(중립)", () => {
    expect(unpassedBadge([row(1, "scored"), row(2, "pending")])).toEqual({ label: "채점 중", tone: "neutral" });
  });

  it("시도 순서는 배열 순서가 아니라 번호로 본다", () => {
    expect(unpassedBadge([row(2, "pending", "no_key"), row(1, "scored")]).label).toBe("채점 대기");
  });

  it("마지막 시도가 반려면 「미통과」", () => {
    expect(unpassedBadge([row(1, "pending", "rejected")])).toEqual({ label: "미통과", tone: "error" });
  });
});
