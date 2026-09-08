"use client";

// 헤더의 벨(`components/notification-bell.tsx`)과 알림 목록 화면
// (`console/notifications/page.tsx`)은 서로 다른 곳에 마운트된 별개의
// 클라이언트 컴포넌트다 — 목록 화면이 "지금 보인 것을 전부 읽음으로
// 표시했다"를 벨에게 즉시 알릴 state가 둘 사이에 없다(#230).
//
// 그래서 `window` 커스텀 이벤트로 아주 얇게 잇는다: 목록 화면이 읽음 처리에
// 성공하면 `broadcastNotificationsRead()`를 부르고, 벨은
// `subscribeToNotificationsRead()`로 듣고 있다가 배지를 다시 읽는다. 벨은
// 어차피 경로 이동·주기적 폴링으로도 다시 읽으므로(그 자체로 최종적으로는
// 맞는 값에 수렴한다) 이 이벤트가 없어도 틀리지 않는다 — 이건 "같은 탭 안에서
// 배지가 곧바로 사라지는" 체감을 위한 지름길일 뿐이다.
const EVENT_NAME = "laurio:notifications-read";

export function broadcastNotificationsRead(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(EVENT_NAME));
}

export function subscribeToNotificationsRead(handler: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(EVENT_NAME, handler);
  return () => window.removeEventListener(EVENT_NAME, handler);
}
