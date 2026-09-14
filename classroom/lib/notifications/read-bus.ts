"use client";

// 헤더의 종(`app/components/notification-bell.tsx`)과 알림 목록 화면
// (`app/notifications/page.tsx`)을 잇는다 — 공개 앱(frontend/lib/notifications/
// read-bus.ts)과 같은 이유·같은 모양이다: 목록 화면이 "지금 보인 것을 전부
// 읽음으로 표시했다"를 종에게 즉시 알려줄 state가 둘 사이에 없어서, `window`
// 커스텀 이벤트로 아주 얇게 잇는다. 종은 폴링으로도 결국 맞는 값에
// 수렴하므로 이 이벤트가 없어도 틀리지 않는다 — 배지가 곧바로 사라지는
// 체감을 위한 지름길일 뿐이다.
const EVENT_NAME = "codemit-classroom:notifications-read";

export function broadcastNotificationsRead(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(EVENT_NAME));
}

export function subscribeToNotificationsRead(handler: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(EVENT_NAME, handler);
  return () => window.removeEventListener(EVENT_NAME, handler);
}
