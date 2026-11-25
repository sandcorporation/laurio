import { describe, expect, it } from "vitest";

import type { SubmitBlockedReason } from "./api";
import { blockedChange } from "./blocked-change";

const REASONS: SubmitBlockedReason[] = [null, "archived", "expelled", "left", "hidden"];

describe("blockedChange", () => {
  for (const before of REASONS) {
    for (const after of REASONS) {
      const name = `${before ?? "열림"} → ${after ?? "열림"}`;
      it(name, () => {
        const change = blockedChange(before, after);
        if (before === after) {
          expect(change).toEqual({ note: "", focus: "none" });
        } else if (before === null) {
          expect(change).toEqual({ note: "", focus: "blocked-note-always" });
        } else if (after === null) {
          expect(change.note).not.toBe("");
          expect(change.focus).toBe("form");
        } else {
          // 사유 사이 전환 — 알림이 있고 초점은 새 안내로.
          expect(change.note).not.toBe("");
          expect(change.focus).toBe("blocked-note");
        }
      });
    }
  }
});
