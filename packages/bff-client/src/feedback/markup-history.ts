// 그림 획의 되돌리기·되돌리기 취소 목록과 단축키 판정 (#1320). react 를 보지 않는 순수 모듈 —
// markup.tsx 가 상태로 들고, 단위 시험은 이 모듈을 직접 친다.

export interface StrokeHistory<T> {
  /** 지금 그림에 놓인 획(오래된 것부터). */
  done: T[];
  /** 되돌려서 다시 놓을 수 있는 획(마지막으로 되돌린 것이 끝). */
  undone: T[];
}

export function emptyHistory<T>(): StrokeHistory<T> {
  return { done: [], undone: [] };
}

/** 새 획을 그리면 되돌리기 취소 목록은 비운다. */
export function pushStroke<T>(history: StrokeHistory<T>, stroke: T): StrokeHistory<T> {
  return { done: [...history.done, stroke], undone: [] };
}

export function undoStroke<T>(history: StrokeHistory<T>): StrokeHistory<T> {
  if (history.done.length === 0) return history;
  return { done: history.done.slice(0, -1), undone: [...history.undone, history.done[history.done.length - 1]] };
}

export function redoStroke<T>(history: StrokeHistory<T>): StrokeHistory<T> {
  if (history.undone.length === 0) return history;
  return { done: [...history.done, history.undone[history.undone.length - 1]], undone: history.undone.slice(0, -1) };
}

/** 「지우기」는 두 목록을 모두 비운다 — 지운 뒤에는 되살릴 것이 없다. */
export function clearHistory<T>(): StrokeHistory<T> {
  return emptyHistory<T>();
}

export interface ShortcutEvent {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
}

export interface ShortcutTarget {
  tagName?: string;
  isContentEditable?: boolean;
}

const TEXT_TAGS = new Set(["TEXTAREA", "INPUT", "SELECT"]);

/** Ctrl/Cmd+Z → undo, +Shift → redo. 글 입력칸에 초점이 있으면 브라우저의 글 되돌리기에 맡긴다. */
export function undoShortcut(event: ShortcutEvent, target: ShortcutTarget | null): "undo" | "redo" | null {
  if (!(event.ctrlKey || event.metaKey) || event.altKey) return null;
  if (event.key.toLowerCase() !== "z") return null;
  if (target && (target.isContentEditable || (target.tagName && TEXT_TAGS.has(target.tagName.toUpperCase())))) return null;
  return event.shiftKey ? "redo" : "undo";
}
