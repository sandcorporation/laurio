// BFF 프록시 허용목록 (ADR-0016, #276/#278) — 공개 앱·운영자 앱과 같은 검사
// 로직을 공유 패키지에서 쓰지만(ADR-0021) **목록의 내용은 이 파일 하나뿐이고
// 이 앱 안에만 있다.**
//
// 기본은 거부다: 새 backend 엔드포인트가 생겨도 여기 추가하기 전에는 이
// 프록시를 통과하지 못한다. `/api/classroom`이 Class·Problem·체크리스트·
// 제출(#286) 전부를 덮는다(backend/config/api.py의 `api.add_router("/classroom",
// ...)` 그대로).
//
// `/api/accounts`·`/api/storage`는 공유층 엔드포인트다(#286) — 참여자가 소스를
// 낼 때 자기 User pk로 target_ref를 조립해야 해서(`GET /api/accounts/me`) 열고,
// 그 소스 파일 자체를 storage에 직접 올려야 해서(`POST /api/storage/uploads`)
// 연다. 공개 앱(frontend/lib/proxy/allowlist.ts)이 같은 이유로 이미 열어 둔
// 접두어 둘을 그대로 옮겨 적었다 — "/api/auth/*"(소셜 로그인)는 이 앱에
// 자기 로그인 라우트가 없으므로(로그인은 공개 앱 것을 그대로 쓴다, docs/
// features/classroom.md) 필요 없다.
//
// `/api/notifications`는 헤더 종·전용 화면이 쓴다(#304) — `/me`·`/unread-count`·
// `/mark-read` 전부 `classroom_only=true`를 붙여 부른다(backend
// `notifications/api.py`). 엔드포인트 자체가 언제나 `request.auth_user`로만
// 걸러 응답하므로, 이 접두어를 여는 것 자체가 남의 알림에 닿는 길을 열지
// 않는다 — 열려도 보이는 건 자기 계정의 알림뿐이다.
import { isAllowedPath } from "@laurio/bff-shared";

export const BACKEND_PROXY_ALLOWLIST: readonly string[] = [
  "/api/classroom",
  "/api/accounts",
  "/api/storage",
  "/api/notifications",
];

export function isAllowedBackendPath(pathname: string): boolean {
  return isAllowedPath(pathname, BACKEND_PROXY_ALLOWLIST);
}
