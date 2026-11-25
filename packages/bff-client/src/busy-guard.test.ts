import { describe, expect, it } from "vitest";

import { BUSY_BUTTON_SELECTOR, isBlockedByBusyButton } from "./busy-guard-core";

describe("isBlockedByBusyButton", () => {
  it("aria-disabled 단추 안의 누름은 막는다", () => {
    const seen: string[] = [];
    const target = { closest: (s: string) => (seen.push(s), {}) };
    expect(isBlockedByBusyButton(target)).toBe(true);
    expect(seen).toEqual([BUSY_BUTTON_SELECTOR]);
  });
  it("그 밖의 누름은 막지 않는다", () => {
    expect(isBlockedByBusyButton({ closest: () => null })).toBe(false);
    expect(isBlockedByBusyButton(null)).toBe(false);
    expect(isBlockedByBusyButton(document_less())).toBe(false);
  });
});

function document_less() {
  return {};
}
