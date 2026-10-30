import { describe, expect, it } from "vitest";

import { formatLatencyTick, formatPercentTick, formatSecondsTick, statusClass, statusClassSeries } from "./series";
import type { RequestBucket } from "./types";

const bucket = (statuses: { status: number; count: number }[]) => ({ statuses }) as unknown as RequestBucket;

describe("statusClassSeries", () => {
  it("상태코드를 클래스로 접고 버킷 수를 지킨다", () => {
    const s = statusClassSeries([bucket([{ status: 200, count: 3 }, { status: 204, count: 1 }, { status: 502, count: 2 }]), bucket([])]);
    expect(s["2xx"]).toEqual([4, 0]);
    expect(s["5xx"]).toEqual([2, 0]);
    expect(s["4xx"]).toEqual([0, 0]);
  });
  it("빈 배열", () => {
    expect(statusClassSeries([])["2xx"]).toEqual([]);
  });
  it("묶음 밖 코드는 other", () => {
    expect(statusClass(101)).toBe("other");
    expect(statusClass(404)).toBe("4xx");
  });
});

describe("formatPercentTick", () => {
  it("정수는 그대로, 소수는 한 자리", () => {
    expect(formatPercentTick(0.05)).toBe("5%");
    expect(formatPercentTick(0.0125)).toBe("1.3%");
    expect(formatPercentTick(0)).toBe("0%");
  });
});

describe("눈금 포맷", () => {
  it("초·분·ms", () => {
    expect(formatSecondsTick(0)).toBe("0");
    expect(formatSecondsTick(25)).toBe("25초");
    expect(formatSecondsTick(400)).toBe("6.7분");
    expect(formatLatencyTick(0.15)).toBe("150ms");
    expect(formatLatencyTick(2)).toBe("2초");
  });
});
