import { describe, expect, it } from "vitest";

import { readCostTableOpen, writeCostTableOpen } from "./cost-table-open";

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => void values.delete(key),
    setItem: (key, value) => void values.set(key, value),
  };
}

const broken = {
  getItem: () => {
    throw new Error("SecurityError");
  },
  setItem: () => {
    throw new Error("QuotaExceededError");
  },
} as unknown as Storage;

describe("비용 표 펼침 상태 (#619)", () => {
  it("처음에는 접혀 있고, 펼치면 그 브라우저가 기억한다", () => {
    const storage = memoryStorage();
    expect(readCostTableOpen(storage)).toBe(false);
    writeCostTableOpen(storage, true);
    expect(readCostTableOpen(storage)).toBe(true);
    writeCostTableOpen(storage, false);
    expect(readCostTableOpen(storage)).toBe(false);
  });

  it("저장소를 못 쓰면 접힘으로 — 던지지 않는다", () => {
    expect(readCostTableOpen(broken)).toBe(false);
    expect(readCostTableOpen(null)).toBe(false);
    expect(() => writeCostTableOpen(broken, true)).not.toThrow();
    expect(() => writeCostTableOpen(null, true)).not.toThrow();
  });
});
