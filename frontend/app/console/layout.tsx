// 인증 구역 레이아웃(ADR-0015) — 이 아래 전부가 클라이언트 SPA다. 서버
// 컴포넌트·서버 액션을 쓰지 않는다: 미들웨어(frontend/middleware.ts)가 이미
// "쿠키가 아예 없으면 렌더링 전에 /login으로 보낸다"를 지키므로, 이 레이아웃과
// 그 아래 페이지들이 서버에서 사용자 토큰을 다룰 일이 애초에 없다.
import type { ReactNode } from "react";

export default function AppLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
