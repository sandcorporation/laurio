// "next" 목적지 검증(#95, spec #92) — 서버(라우트 핸들러)와 클라이언트(로그인
// 화면이 실물 카카오 버튼의 href를 조립할 때) 양쪽에서 쓴다. Node 전용 API를
// 쓰지 않는다 — lib/auth/oauth-state.ts가 이 파일과 별개인 이유가 그것이다:
// 그쪽은 node:crypto(randomBytes)를 쓰는 서버 전용 코드라, 클라이언트 컴포넌트인
// app/login/login-form.tsx가 그 모듈을 그대로 import하면 webpack이 브라우저
// 번들에 node:crypto를 끌고 가려다 빌드가 깨진다(직접 재현해 확인했다) — 순수
// 검증 로직만 이 파일로 분리해 그 경로를 피한다.
export function isSafeNextPath(next: string | null | undefined): next is string {
  if (!next) return false;
  if (!next.startsWith("/")) return false;
  if (next.startsWith("//")) return false;
  if (next.includes("://")) return false;
  return true;
}

export function resolveNextPath(next: string | null | undefined, fallback = "/console"): string {
  return isSafeNextPath(next) ? next : fallback;
}
