// 제보 창 그림의 되돌리기·되돌리기 취소와 단축키 판정 (#1320).
import { describe, expect, it } from "vitest";

import {
  clearHistory,
  emptyHistory,
  pushStroke,
  redoStroke,
  undoShortcut,
  undoStroke,
  type ShortcutEvent,
} from "@codemit/bff-client/feedback-history";

const key = (over: Partial<ShortcutEvent>): ShortcutEvent => ({
  key: "z", ctrlKey: true, metaKey: false, altKey: false, shiftKey: false, ...over,
});

describe("undoShortcut", () => {
  it("Ctrl+Z 는 되돌리기, Ctrl+Shift+Z 는 되돌리기 취소", () => {
    expect(undoShortcut(key({}), null)).toBe("undo");
    expect(undoShortcut(key({ shiftKey: true, key: "Z" }), null)).toBe("redo");
  });
  it("Cmd 도 받는다", () => {
    expect(undoShortcut(key({ ctrlKey: false, metaKey: true }), null)).toBe("undo");
    expect(undoShortcut(key({ ctrlKey: false, metaKey: true, shiftKey: true }), null)).toBe("redo");
  });
  it("글 입력칸 초점이면 가로채지 않는다", () => {
    expect(undoShortcut(key({}), { tagName: "TEXTAREA" })).toBeNull();
    expect(undoShortcut(key({}), { tagName: "input" })).toBeNull();
    expect(undoShortcut(key({}), { tagName: "DIV", isContentEditable: true })).toBeNull();
    expect(undoShortcut(key({}), { tagName: "BUTTON" })).toBe("undo");
  });
  it("수정키 없는 z·다른 키·Alt 조합은 무시한다", () => {
    expect(undoShortcut(key({ ctrlKey: false }), null)).toBeNull();
    expect(undoShortcut(key({ key: "y" }), null)).toBeNull();
    expect(undoShortcut(key({ altKey: true }), null)).toBeNull();
  });
});

describe("획 목록", () => {
  it("되돌린 획을 다시 놓는다", () => {
    let h = pushStroke(pushStroke(emptyHistory<string>(), "a"), "b");
    h = undoStroke(h);
    expect(h).toEqual({ done: ["a"], undone: ["b"] });
    h = redoStroke(h);
    expect(h).toEqual({ done: ["a", "b"], undone: [] });
  });
  it("새 획을 그리면 되돌리기 취소 목록이 빈다", () => {
    const h = pushStroke(undoStroke(pushStroke(emptyHistory<string>(), "a")), "c");
    expect(h).toEqual({ done: ["c"], undone: [] });
  });
  it("지우기는 두 목록을 모두 비운다", () => {
    expect(clearHistory()).toEqual({ done: [], undone: [] });
  });
  it("빈 목록에서 되돌리기·취소는 그대로다", () => {
    const h = emptyHistory<string>();
    expect(undoStroke(h)).toBe(h);
    expect(redoStroke(h)).toBe(h);
  });
});
