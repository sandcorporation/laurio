"use client";

// 공개 앱의 BFF 클라이언트 — 앱이 주입하는 것은 인증 방식뿐이다 (#146, #122).
//
// - `revive`: `/api/auth/session` 은 액세스가 만료돼 있으면 조용히 리프레시한다(FE-07, #32). 그
//   라우트를 한 번 부르는 것이 곧 「세션 되살리기」이고, 단일 비행·재시도는 패키지가 소유한다.
// - `onUnauthorized`: 되살려도 401 이면 로그인으로 보낸다. **`?next=` 를 항상 붙인다** — 예전에는
//   `use-session` 하나만 붙이고 나머지는 안 붙여, 세션이 죽은 사람이 로그인 뒤 홈으로 떨어졌다.
//   전체 페이지 이동(`window.location`)인 이유는 둘이다: 세션이 죽은 뒤 React 트리를 살려 둘 이유가
//   없고, 훅 밖(변경 호출 함수)에서도 같은 클라이언트를 써야 해 `useRouter` 에 묶을 수 없다.

import { createBffClient, createLoginRedirect } from "@codemit/bff-client";

// 한 화면의 요청 여럿이 함께 401 을 받아도 이동은 한 번이다(#501, 패키지의 `login-redirect`).
const goToLogin = createLoginRedirect();

export const bffClient = createBffClient({
  revive: () => fetch("/api/auth/session", { cache: "no-store" }),
  onUnauthorized: goToLogin,
});
