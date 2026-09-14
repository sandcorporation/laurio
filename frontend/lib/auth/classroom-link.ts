// 헤더 계정 메뉴의 「클래스로 가기」 목적지(#375, spec #371). 이 값은
// `LAURIO_CLASSROOM_ORIGIN`에서 온다 — 강의실 컨테이너가 자기 오리진을 알리는
// 것과 **같은 `.env` 줄**이다(`LAURIO_OPERATOR_ORIGIN`과 같은 원칙,
// `sibling-origins.ts`가 반대 방향(형제 오리진 허용목록)으로 이미 읽는 값이다).
//
// **여기서는 검증하지 않는다.** `sibling-origins.ts`의 `resolveSiblingOrigin`은
// 사용자가 준 후보값이 우리 형제 오리진인지 판정하는 함수이고, 이 함수는 반대로
// 우리가 신뢰하는 배포 설정을 그대로 읽어 내보내는 값이다 — 검증할 후보가
// 애초에 없다.
//
// **`process.env`를 직접 읽으므로 서버 컴포넌트에서만 부를 수 있다** — 값이
// `NEXT_PUBLIC_`이 아니라 브라우저 번들에 실리지 않는다. dev는 이 값을 비워
// 두므로(`docker/compose.dev.yaml`) CLAUDE.md 포트 표의 강의실 기본값(오프셋 0)
// 으로 떨어진다 — classroom의 `publicAppOrigin()`(`classroom/lib/auth/
// public-app.ts`)이 반대 방향으로 쓰는 것과 같은 폴백이다.
//
// **이 값을 읽는 페이지/레이아웃은 빌드 시점에 구워지면 안 된다**(#297) —
// `frontend/app/layout.tsx`의 `force-dynamic`, `lib/rendering/
// runtime-config.test.ts`가 그 구조를 지킨다.
export function classroomAppOrigin(): string {
  return process.env.LAURIO_CLASSROOM_ORIGIN || "http://127.0.0.1:53002";
}
