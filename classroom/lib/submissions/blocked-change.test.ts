import { describe, expect, it } from "vitest";

import type { SubmitBlockedReason } from "./api";
import { blockedChange } from "./blocked-change";

const REASONS: SubmitBlockedReason[] = [null, "archived", "expelled", "left", "hidden"];

// 사유 사이 전환은 현재 사유로 알린다 — 백엔드는 우선순위대로 하나만 돌려주니(보관 → 내보냄 → 숨김)
// 우선순위가 바뀐 것을 이전 사유가 풀렸다고 추론하지 않는다.
const NOW: Record<NonNullable<SubmitBlockedReason>, string> = {
  archived: "클래스가 보관돼 제출할 수 없습니다.",
  expelled: "클래스에서 내보내져 제출할 수 없습니다.",
  left: "클래스에서 나가 제출할 수 없습니다.",
  hidden: "문제가 숨겨져 제출할 수 없습니다.",
};
const RELEASED: Record<NonNullable<SubmitBlockedReason>, string> = {
  archived: "보관이 풀려 다시 제출할 수 있습니다.",
  expelled: "이 클래스에 다시 들어와 제출할 수 있습니다.",
  left: "이 클래스에 다시 들어와 제출할 수 있습니다.",
  hidden: "문제가 다시 열려 제출할 수 있습니다.",
};

describe("blockedChange", () => {
  for (const before of REASONS) {
    for (const after of REASONS) {
      const name = `${before ?? "열림"} → ${after ?? "열림"}`;
      it(name, () => {
        const change = blockedChange(before, after);
        if (before === after) {
          expect(change).toEqual({ note: "", focus: "none" });
        } else if (before === null) {
          expect(change).toEqual({ note: "", focus: "blocked-note" });
        } else if (after === null) {
          expect(change).toEqual({ note: RELEASED[before], focus: "form" });
        } else {
          expect(change).toEqual({ note: NOW[after], focus: "blocked-note" });
          // 이전 사유가 풀렸다는 말은 없다.
          expect(change.note).not.toMatch(/풀렸|다시 열|다시 들어/);
        }
      });
    }
  }
});
