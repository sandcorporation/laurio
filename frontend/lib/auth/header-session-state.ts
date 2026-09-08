// 헤더의 세션 판정 결과 — 값만 담는다(#237).
//
// `header-session-zone.tsx`가 이 상태를 한 번만 확인해 `NotificationBell`과
// `SessionSlot`에 나눠 준다. 두 컴포넌트가 이 타입만 알면 되고, 어떻게
// 확인했는지(어느 클라이언트로 어느 경로를 불렀는지)는 몰라도 된다 — 그래서
// 순환 임포트 없이 셋이 이 파일 하나를 같이 본다.
export type HeaderSessionState =
  | { status: "loading" }
  | { status: "authenticated" }
  | { status: "unauthenticated" };
