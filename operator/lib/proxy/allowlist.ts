import { isAllowedPath } from "@laurio/bff-shared";

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

export function isAllowedBackendPath(pathname: string): boolean {
  return isAllowedPath(pathname, OPERATOR_BACKEND_PROXY_ALLOWLIST);
}
