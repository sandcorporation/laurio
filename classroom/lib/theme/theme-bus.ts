"use client";

// 헤더의 테마 버튼(`components/theme-toggle.tsx`)과 문제 설명 에디터
// (`components/MarkdownEditor.tsx`, #399)는 서로 다른 곳에 마운트된 별개의
// 클라이언트 컴포넌트다 — 토글이 문서 루트의 data-theme 를 바꿔도 에디터가
// 그 변화를 알 방법이 DOM 이벤트 말고는 없다(알림 벨의 read-bus.ts 와 같은
// 이유, #230).
const EVENT_NAME = "codemit:theme-change";

export function broadcastThemeChange(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(EVENT_NAME));
}

export function subscribeToThemeChange(handler: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(EVENT_NAME, handler);
  return () => window.removeEventListener(EVENT_NAME, handler);
}
