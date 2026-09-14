import { isAllowedPath } from "@codemit/bff-shared";

// 운영자 앱의 BFF 프록시 허용목록(#64, ADR-0021). 검사 로직은 공유 패키지 것을
// 쓰지만(frontend/lib/proxy/allowlist.ts와 같은 방식) **목록의 내용은 이 파일
// 하나뿐이고 이 앱 안에만 있다.**
//
// 운영자 표면 하나가 전부다 — 내부 스캔 표면(`/api/internal/*`)은 사람이 아니라
// Celery beat 가 부르는 자리라 여기서도 막는다(공개 앱의 허용목록과 같은 이유).
// `/api/ledger/*` 는 백엔드의 SESSION_AUTHENTICATED_PREFIXES에 들어 있지만
// (core/operator_auth.py) 이 스펙의 「할 일」 세 큐에 들어가지 않으므로(스펙
// Out of Scope: "원장 직접 조회 화면") 이 목록에도 없다 — 필요해지면 그때
// 명시적으로 연다.
export const OPERATOR_BACKEND_PROXY_ALLOWLIST: readonly string[] = ["/api/operator"];

// 로그인·로그아웃은 이 접두어 안에 있지만 범용 프록시를 태우면 안 된다(코드리뷰
// 지적) — 공개 앱이 "/api/auth/*"를 허용목록에서 뺀 것과 같은 자리다. 다른 점은
// 공개 앱에서는 그게 구조적으로 다른 접두어("/api/accounts" vs "/api/auth")라
// 저절로 안 겹치는데, 여기서는 로그인·로그아웃이 "/api/operator" 바로 그 접두어
// 아래 있어서 명시적으로 빼야 한다.
//
// **왜 위험한가.** Django의 `login()`은 세션 고정 공격을 막으려고
// `request.session.cycle_key()`를 불러 세션 id를 갈아치우고 새 Set-Cookie를
// 낸다. 전용 라우트(app/api/auth/login/route.ts)는 그 Set-Cookie를 파싱해 이 앱
// 자신의 쿠키로 다시 굽지만, 범용 프록시(app/api/backend/[...path])는 백엔드
// 응답의 Set-Cookie를 그냥 버린다 — 원래 다른 세션 인증(예: 참가자 JWT처럼
// Authorization 헤더만 오가는 API)을 전제로 만들어졌기 때문이다. 그래서 로그인이
// 이 경로로 새면 Django 쪽 세션은 새 id로 바뀌는데 브라우저 쿠키는 옛 id로 남아
// **조용히 로그아웃된 것과 같은 상태**가 된다. 로그아웃도 같은 이유로 막는다 —
// 전용 라우트가 이미 성공 시에만 쿠키를 지우는 정확한 처리를 하고 있다.
const EXCLUDED_EXACT_PATHS: ReadonlySet<string> = new Set([
  "/api/operator/login",
  "/api/operator/logout",
]);

export function isAllowedBackendPath(pathname: string): boolean {
  if (EXCLUDED_EXACT_PATHS.has(pathname)) return false;
  return isAllowedPath(pathname, OPERATOR_BACKEND_PROXY_ALLOWLIST);
}
