import { describe, expect, it } from "vitest";

import { joinLinkAvailability } from "./join-link";

describe("joinLinkAvailability", () => {
  it("진행중 클래스는 active", () => {
    expect(joinLinkAvailability(false)).toBe("active");
  });

  it("보관된 클래스는 archived", () => {
    expect(joinLinkAvailability(true)).toBe("archived");
  });
});
