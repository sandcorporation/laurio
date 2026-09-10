// BFF 프록시 허용목록 (ADR-0016, #276/#278) — 공개 앱·운영자 앱과 같은 검사
// 로직을 공유 패키지에서 쓰지만(ADR-0021) **목록의 내용은 이 파일 하나뿐이고
// 이 앱 안에만 있다.**
//
// 기본은 거부다: 새 backend 엔드포인트가 생겨도 여기 추가하기 전에는 이
// 프록시를 통과하지 못한다. `/api/classroom`이 Class·Problem·체크리스트
// 전부를 덮는다(backend/config/api.py의 `api.add_router("/classroom", ...)`
// 그대로) — accounts처럼 공유층 엔드포인트가 필요해지면 그것도 여기 추가한다.
import { isAllowedPath } from "@laurio/bff-shared";

export const BACKEND_PROXY_ALLOWLIST: readonly string[] = ["/api/classroom"];

export function isAllowedBackendPath(pathname: string): boolean {
  return isAllowedPath(pathname, BACKEND_PROXY_ALLOWLIST);
}
